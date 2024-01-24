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
              'database':'simulator_20231020',
              'user':'student',
              'password':'_'}

# Дефолтные параметры
default_args = {
    'owner': 't-demkina',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'start_date': datetime(2022, 3, 10),
}

# Интервал запуска DAG
schedule_interval = '0 11 * * *'

@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def dag_alert_tdemkina():
   
    # Выгружаем данные для текстового сообщения
    @task
    def extract_text():
        query_text = '''SELECT 
                            COUNT(DISTINCT user_id) as DAU,
                            SUM(action = 'view') as views,
                            SUM(action  = 'like') as likes,
                            round(likes/views, 2) as CTR
                        FROM 
                            simulator_20231020.feed_actions 
                        WHERE 
                            toDate(time) = today() - 1'''
        df_text = ph.read_clickhouse(query = query_text, connection=connection)
        return df_text
    
    # Выгружаем данные для графиков
    @task
    def extract_chart():
        query_chart = '''SELECT 
                             toDate(time) as date,
                             COUNT(DISTINCT user_id) as DAU,
                             SUM(action = 'view') as views,
                             SUM(action  = 'like') as likes,
                             round(likes/views, 4) as CTR
                         FROM 
                             simulator_20231020.feed_actions 
                         WHERE 
                             toDate(time) BETWEEN today() - 7 AND today()-1
                         GROUP BY 
                             toDate(time)'''
        df_chart = ph.read_clickhouse(query = query_chart, connection=connection)
        return df_chart
   
    # Составляем текст отчета
    @task
    def transform_text(df_text):
        date = datetime.now() - timedelta(days=1)
        date_format = date.strftime('%Y-%m-%d')
        
        text_date = f'Ключевые метрики за {date_format}:'
        text_dau = f'DAU - {df_text.DAU[0]:,}'
        text_views = f'Просмотры - {df_text.views[0]:,}'
        text_likes = f'Лайки - {df_text.likes[0]:,}'
        text_ctr = f'CTR - {df_text.CTR[0]:,}'
        
        combined_text = f"""{text_date}\n{text_dau}\n{text_views}\n{text_likes}\n{text_ctr}"""
        return combined_text
    
    # Строим графики для отчета
    @task
    def transform_plot(df_chart):
        fig, ax = plt.subplots(nrows=3, ncols=1, figsize=(10, 15))

        # for dau
        x = df_chart.date
        y = df_chart.DAU
        sns.lineplot(x=x, y=y, ax=ax[0])
        ax[0].set_title('DAU')
        ax[0].grid(True)
        ax[0].set_xlabel('')
        ax[0].set_ylabel('')

        # for actions
        y1 = df_chart.views
        y2 = df_chart.likes
        sns.lineplot(x=x, y=y1, label='Просмотры', ax=ax[1])
        sns.lineplot(x=x, y=y2, label='Лайки', ax=ax[1])
        ax[1].set_title('Views and likes')
        ax[1].grid(True)
        ax[1].set_xlabel('')
        ax[1].set_ylabel('')
        ax[1].legend()

        # for ctr
        y3 = df_chart.CTR
        sns.lineplot(x=x, y=y3, ax=ax[2])
        ax[2].set_title('CTR')
        ax[2].tick_params(axis='x')
        ax[2].grid(True)
        ax[2].set_xlabel('')
        ax[2].set_ylabel('')
        sns.despine(ax=ax[2])

        plot_object_plot = io.BytesIO()
        plt.tight_layout()
        plt.savefig(plot_object_plot)
        plot_object_plot.seek(0)
        plot_object_plot.name = 'combined_plots.png'
        plt.close()
        return plot_object_plot
    
    # Отправляем отчет через телеграм-бота
    @task
    def load(combined_text, plot_object_plot):
        my_token = '_'
        bot = telegram.Bot(token=my_token)
        chat_id = _
        
        send_text = bot.sendMessage(chat_id=chat_id, text=combined_text)
        send_plot = bot.sendPhoto(chat_id=chat_id, photo=plot_object_plot)
        print(send_text, send_plot)
        
    df_text = extract_text()
    df_chart = extract_chart()
    
    combined_text = transform_text(df_text)
    plot_object_plot = transform_plot(df_chart)
    load(combined_text, plot_object_plot)

dag_alert_tdemkina = dag_alert_tdemkina()