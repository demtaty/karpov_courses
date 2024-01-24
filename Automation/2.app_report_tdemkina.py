import pandahouse as ph
from datetime import datetime, timedelta
import pandas as pd

from airflow.decorators import dag, task

import telegram
import matplotlib.pyplot as plt
import seaborn as sns
import io
import pandahouse as ph

connection = {'host': 'https://clickhouse.lab.karpov.courses', 
              'database': 'simulator_20231020', 
              'user': 'student', 
              'password': '_'}

default_args = {'owner': 't-demkina', 
                'depends_on_past': False,
                'retries': 2, 
                'retry-delay': timedelta(minutes=5), 
                'start_date': datetime(2023, 11, 14)
               }

schedule_interval = '0 11 * * *'

@dag(default_args = default_args, schedule_interval = schedule_interval, catchup = False)
def app_report_tdemkina():

    @task
    def extract_feed():
        query_feed = '''SELECT 
                            date, 
                            DAU_feed, 
                            posts, 
                            views, 
                            likes, 
                            CTR, 
                            users_org, 
                            users_ads
                        FROM 
                          (
                          SELECT 
                            toDate(time) as date,
                            COUNT(DISTINCT user_id) as DAU_feed,
                            COUNT(DISTINCT post_id) as posts,
                            SUM(action = 'view') as views,
                            SUM(action  = 'like') as likes,
                            round(likes/views, 4) as CTR
                          FROM 
                              simulator_20231020.feed_actions 
                          WHERE 
                              toDate(time) BETWEEN toStartOfMonth(today()) - 30 AND today()-1
                          GROUP BY 
                              toDate(time)
                          ) as feed
                        JOIN
                          (
                          SELECT 
                              date, 
                              users_org, 
                              users_ads
                          FROM 
                              (
                              SELECT 
                                   toDate(time) as date,
                                   COUNT(DISTINCT user_id) as users_org
                               FROM 
                                   simulator_20231020.feed_actions 
                               WHERE 
                                   source = 'organic'
                               GROUP BY 
                                   toDate(time)
                               ) as t1
                          LEFT JOIN
                              (
                              SELECT 
                                  toDate(time) as date,
                                  COUNT(DISTINCT user_id) as users_ads
                              FROM 
                                  simulator_20231020.feed_actions 
                              WHERE 
                                  source = 'ads'
                              GROUP BY 
                                  toDate(time)
                              ) as t2 ON t1.date = t2.date
                        ) as source ON feed.date = source.date
                          ORDER BY 
                              date DESC'''
        df_feed = ph.read_clickhouse(query = query_feed, connection=connection)
        return df_feed

    @task
    def extract_mes():
        query_mes = '''SELECT
                          date,
                          DAU_mes,
                          messages_sent,
                          DAU_mes_organic,
                          DAU_mes_ads
                        FROM
                          (
                            SELECT
                              toDate(time) as date,
                              COUNT(DISTINCT user_id) as DAU_mes,
                              COUNT(receiver_id) as messages_sent
                            FROM
                              simulator_20231020.message_actions
                            WHERE
                              toDate(time) BETWEEN toStartOfMonth(today()) - 30 AND today() -1
                            GROUP BY
                              toDate(time)
                          ) as mm1
                          JOIN (
                            SELECT
                              date,
                              DAU_mes_organic,
                              DAU_mes_ads
                            FROM
                              (
                                SELECT
                                  toDate(time) as date,
                                  COUNT(DISTINCT user_id) as DAU_mes_organic,
                                  COUNT(receiver_id) as messages_sent
                                FROM
                                  simulator_20231020.message_actions
                                WHERE
                                  source = 'organic'
                                GROUP BY
                                  toDate(time)
                              ) as m1
                              JOIN (
                                SELECT
                                  toDate(time) as date,
                                  COUNT(DISTINCT user_id) as DAU_mes_ads,
                                  COUNT(receiver_id) as messages_sent
                                FROM
                                  simulator_20231020.message_actions
                                WHERE
                                  source = 'ads'
                                GROUP BY
                                  toDate(time)
                              ) as m2 ON m1.date = m2.date
                          ) as mm2 ON mm1.date = mm2.date
                        ORDER BY
                          date DESC'''
        df_mes = ph.read_clickhouse(query = query_mes, connection=connection)
        return df_mes
    
    # Определяем диапозон дат (новости)
    @task
    def transform_last_week_feed(df_feed):
        end_date = df_feed['date'][0].strftime('%Y-%m-%d')
        start_date = df_feed['date'][6].strftime('%Y-%m-%d')
        last_week_feed = df_feed[(df_feed['date'] >= start_date) & (df_feed['date'] <= end_date)].reset_index(drop=True)
        return last_week_feed
        
    # Определяем диапозон дат (мессенджер)
    @task
    def transform_last_week_mes(df_mes):
        end_date = df_mes['date'][0].strftime('%Y-%m-%d')
        start_date = df_mes['date'][6].strftime('%Y-%m-%d')
        last_week_mes = df_mes[(df_mes['date'] >= start_date) & (df_mes['date'] <= end_date)].reset_index(drop=True)
        return last_week_mes
    
    # Формируем сообщение по метрикам всего приложения
    @task
    def transform_metric(df_feed, df_mes):
        df_feed['month'] = df_feed.date.dt.month
        end_date = df_feed['date'][0].strftime('%Y-%m-%d')
        
        users_feed = df_feed.DAU_feed.reset_index(drop=True)[0]
        user_mes = df_mes.DAU_mes[0]
        changes_view = round((df_feed.views.reset_index(drop=True)[0] * 100 /df_feed.views.reset_index(drop=True)[1]) - 100, 2)
        changes_like = round((df_feed.likes.reset_index(drop=True)[0] * 100 /df_feed.likes.reset_index(drop=True)[1]) - 100, 2)
        changes_post = round((df_feed.posts.reset_index(drop=True)[0] * 100 /df_feed.posts.reset_index(drop=True)[1]) - 100, 2)
        changes_ctr = round((df_feed.CTR.reset_index(drop=True)[0] * 100 /df_feed.CTR.reset_index(drop=True)[1]) - 100, 2)
        changes_mes_sent = round((df_mes.messages_sent[0] * 100 /df_mes.messages_sent[1]) - 100, 2)
        
        title = f'Отчет по работе приложения:'
        user = f'Пользователи за {end_date}, которые посетили:'
        user_1 = f'- ленту новостей - {users_feed:,} чел.,' 
        user_2 = f'- ленту сообщений - {user_mes:,} чел.'
        title_2 = f'Изменение по ключевым метрикам за {end_date} по сравнению с предыдущим днем:'
        view = f'- просмотры {changes_view}%,'
        like = f'- лайки {changes_like}%,'
        post = f'- посты {changes_post}%,'
        ctr = f'- ctr {changes_ctr}%,'
        mes = f'- отправленные сообщения {changes_mes_sent}%'
        
        combined_text = f"""{title}\n\n{user}\n{user_1}\n{user_2}\n\n{title_2}\n{view}\n{like}\n{post}\n{ctr}\n{mes}"""
        return combined_text
        
    # Формируем графики по работе приложения - 1 часть
    @task
    def dau_plots(last_week_feed, last_week_mes):
        end_date = last_week_feed['date'][0].strftime('%Y-%m-%d')
        start_date = last_week_feed['date'][6].strftime('%Y-%m-%d')
        
        fig, ax = plt.subplots(nrows=1, ncols=2, figsize=(20, 9))

        # feeds
        x = last_week_feed.date
        y = last_week_feed.users_org
        y1 = last_week_feed.users_ads
        sns.lineplot(x=x, y=y, ax=ax[0], label='organic')
        sns.lineplot(x=x, y=y1, ax=ax[0], label='ads')
        ax[0].set_title('DAU лента новостей', fontsize=14)
        ax[0].grid(True)
        ax[0].set_xlabel('')
        ax[0].set_ylabel('')

        # messeges
        x1 = last_week_mes.date
        y2 = last_week_mes.DAU_mes_organic
        y3 = last_week_mes.DAU_mes_ads
        sns.lineplot(x=x1, y=y2, ax=ax[1], label='organic')
        sns.lineplot(x=x1, y=y3, ax=ax[1], label='ads')
        ax[1].set_title('DAU лента сообщений', fontsize=14)
        ax[1].grid(True)
        ax[1].set_xlabel('')
        ax[1].set_ylabel('')

        fig.suptitle(f'Динамика пользователей в разбивке по источникам за период с {start_date} по {end_date}', fontsize=19)
        plt.tight_layout()
        users_plots = io.BytesIO()
        plt.savefig(users_plots)
        users_plots.seek(0)
        users_plots.name = 'users_plots.png'
        plt.close()
        return users_plots
        
    # Формируем графики по работе приложения - 2 часть
    @task
    def metrics_plot(last_week_feed, last_week_mes):
        end_date = last_week_feed['date'][0].strftime('%Y-%m-%d')
        start_date = last_week_feed['date'][6].strftime('%Y-%m-%d')
        fig, ax = plt.subplots(nrows=2, ncols=2, figsize=(20, 11))

        # views/likes
        x = last_week_feed.date
        y = last_week_feed.views
        y1 = last_week_feed.likes
        sns.lineplot(x=x, y=y, ax=ax[0,0], label='views')
        sns.lineplot(x=x, y=y1, ax=ax[0,0], label='like')
        ax[0,0].set_title('Views and likes', fontsize=14)
        ax[0,0].grid(True)
        ax[0,0].set_xlabel('')
        ax[0,0].set_ylabel('')

        # ctr
        y2 = last_week_feed.CTR
        sns.lineplot(x=x, y=y2, ax=ax[0,1])
        ax[0,1].set_title('CTR', fontsize=14)
        ax[0,1].grid(True)
        ax[0,1].set_xlabel('')
        ax[0,1].set_ylabel('')

        # messeges
        y3 = last_week_feed.posts
        sns.lineplot(x=x, y=y3, ax=ax[1,1])
        ax[1,1].set_title('Messages sent', fontsize=14)
        ax[1,1].grid(True)
        ax[1,1].set_xlabel('')
        ax[1,1].set_ylabel('')

        # messeges
        x1 = last_week_mes.date
        y4 = last_week_mes.messages_sent
        sns.lineplot(x=x1, y=y4, ax=ax[1,0])
        ax[1,0].set_title('Posts', fontsize=14)
        ax[1,0].grid(True)
        ax[1,0].set_xlabel('')
        ax[1,0].set_ylabel('')

        fig.suptitle(f'Основные метрики по двум лентам за период с {start_date} по {end_date}', fontsize=19)
        plt.tight_layout()
        plots_metrics = io.BytesIO()
        plt.savefig(plots_metrics)
        plots_metrics.seek(0)
        plots_metrics.name = 'main_matrics.png'
        plt.close()
        return plots_metrics
        
    # Отправляем отчет через телеграм-бота
    @task
    def load(combined_text, users_plots, plots_metrics):
        my_token = '_'
        bot = telegram.Bot(token=my_token)
        chat_id = _
        
        send_text = bot.sendMessage(chat_id=chat_id, text=combined_text)
        send_plot_dau = bot.sendPhoto(chat_id=chat_id, photo=users_plots)     
        sent_plot_metric = bot.sendPhoto(chat_id=chat_id, photo=plots_metrics)
        print(send_text, send_plot_dau, sent_plot_metric)
    
    df_feed = extract_feed()
    df_mes = extract_mes()
    
    last_week_feed = transform_last_week_feed(df_feed)
    last_week_mes = transform_last_week_mes(df_mes)
    
    users_plots = dau_plots(last_week_feed, last_week_mes)
    plots_metrics = metrics_plot(last_week_feed, last_week_mes)
    combined_text = transform_metric(df_feed, df_mes)
    load(combined_text, users_plots, plots_metrics)

app_report_tdemkina = app_report_tdemkina()
    
    
    
    
        