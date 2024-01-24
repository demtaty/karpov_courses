import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import pandahouse as ph
from datetime import datetime, timedelta, date

import telegram
import io
import sys
import os

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

connection = {'host': 'https://clickhouse.lab.karpov.courses', 
              'database': 'simulator_20231020', 
              'user': 'student', 
              'password': '_'}

default_args = {'owner': 't-demkina', 
                'depends_on_past': False,
                'retries': 2, 
                'retry-delay': timedelta(minutes=5), 
                'start_date': datetime(2023, 11, 16)
               }

schedule_interval = '*/15 * * * *'

list_metrics_feed = ['users', 'views', 'likes', 'ctr']
list_metrics_mes = ['users_mes', 'sent_messages']

@dag(default_args = default_args, schedule_interval = schedule_interval, catchup = False)
def alert_system_t_demkina():
    
    # Выгружаем данные по ленте новостей
    @task
    def extract_feed():
        data = '''SELECT
                      toStartOfFifteenMinutes(time) as ts,
                      toDate(ts) as date,
                      formatDateTime(ts, '%R') as hm,
                      uniqExact(user_id) as users,
                      SUM(action='view') as views,
                      SUM(action='like') as likes,
                      round(likes/views, 4) as ctr
                    FROM 
                        simulator_20231020.feed_actions
                    WHERE 
                        ts >=  today() - 1
                        AND ts < toStartOfFifteenMinutes(now())
                    GROUP BY 
                        ts, 
                        date, 
                        hm
                    ORDER BY 
                        ts '''
        df_feed = ph.read_clickhouse(query=data, connection=connection)
        return df_feed
    
    # Выгружаем данные по мессенджеру
    @task
    def extract_mes():
        data_mes = '''SELECT 
                          toStartOfFifteenMinutes(time) as ts,
                          toDate(ts) as date,
                          formatDateTime(ts, '%R') as hm,
                          COUNT(DISTINCT user_id) as users,
                          COUNT(receiver_id) as sent_messages
                        FROM 
                            simulator_20231020.message_actions 
                        WHERE 
                            ts >=  today() - 1
                            AND ts < toStartOfFifteenMinutes(now())
                        GROUP BY 
                            ts, 
                            date, 
                            hm
                        ORDER BY 
                        ts'''
        df_mes = ph.read_clickhouse(query=data_mes, connection=connection)
        return df_mes
    
    # Определяем аномалии при помощи межквартильного размаха
    def define_anomaly(df, metric, a=4, n=5):
        df['q25'] = df[metric].shift(1).rolling(n).quantile(0.25)
        df['q75'] = df[metric].shift(1).rolling(n).quantile(0.75)
        df['iqr'] = df['q75'] - df['q25']
        df['top'] = df['q75'] + a * df['iqr']
        df['bottom'] = df['q25'] - a * df['iqr']

        df['top'] = df['top'].rolling(n, center=True, min_periods=1).mean()
        df['bottom'] = df['bottom'].rolling(n, center=True, min_periods=1).mean()
        
        if df[metric].iloc[-1] > df['top'].iloc[-1] or df[metric].iloc[-1] < df['bottom'].iloc[-1]:
            alert = 1
        else:
            alert = 0
        return df, alert
    
    # Формируем условия для отправки алертов и отправляем его через телеграм-бота
    @task
    def run_alert(df, list_metrics):
        chat_id = _
        bot = telegram.Bot(token='_')

        for metric in list_metrics:
            df_ = df[['ts', 'date', 'hm', metric]].copy()
            df_metric, alert = define_anomaly(df_, metric)
            
            if alert == 1:
                # Определяем текст сообщения
                text = '''Метрика {metric}:\nТекущее значение: {curent_value}. Отклонение составило: {last_value:.1%}.'''.format(metric=metric, 
                            curent_value=df_metric[metric].iloc[-1], 
                            last_value=abs(1 - (df_metric[metric].iloc[-1]/df_metric[metric].iloc[-2])))
                
                # строим график
                sns.set(rc={'figure.figsize': (16, 10)})
                plt.tight_layout()

                ax = sns.lineplot(x=df_metric['ts'], y=df_metric[metric], label='metric')
                ax = sns.lineplot(x=df_metric['ts'], y=df_metric['top'], label='top')
                ax = sns.lineplot(x=df_metric['ts'], y=df_metric['bottom'], label='bottom')

                for ind, label in enumerate(ax.get_xticklabels()):
                    if ind % 2 == 0:
                        label.set_visible(True)
                    else:
                        label.set_visible(False)

                ax.set(xlabel='time')
                ax.set(ylabel=metric)

                ax.set_title('{}'.format(metric))
                ax.set(ylim=(0, None))

                plot_object = io.BytesIO()
                ax.figure.savefig(plot_object)
                plot_object.seek(0)
                plot_object.name = '{0}.png'.format(metric)
                plt.close()

                # запускаем телеграм-бота
                bot.sendMessage(chat_id=chat_id, text=text)
                bot.sendPhoto(chat_id=chat_id, photo=plot_object)
    
    df_feed = extract_feed()
    df_mes = extract_mes()
    run_alert(df_feed, list_metrics_feed)
    run_alert(df_mes, list_metrics_mes)

alert_system_t_demkina = alert_system_t_demkina()