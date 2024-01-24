import pandahouse as ph
from datetime import datetime, timedelta
import pandas as pd

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

connection = {'host': 'https://clickhouse.lab.karpov.courses',
              'database':'simulator_20231020',
              'user':'student',
              'password':'_'
             }

connection_test = {'host': 'https://clickhouse.lab.karpov.courses',
                   'database':'test',
                   'user':'student-rw',
                   'password':'_'
                  }

# Дефолтные параметры
default_args = {'owner': 't-demkina',
                'depends_on_past': False,
                'retries': 2,
                'retry_delay': timedelta(minutes=5),
                'start_date': datetime(2022, 3, 10),
               }

# Интервал запуска DAG
schedule_interval = '0 23 * * *'

@dag(default_args=default_args, schedule_interval=schedule_interval, catchup=False)
def dag_etl_tdemkina():

    # Извлекаем данные по кол-ву просмотров и лайков
    @task
    def extract_feed():
        query_feed = """SELECT 
                            user_id,
                            toDate(time) as event_date,
                            SUM(action='view') as views,
                            SUM(action='like') as likes, 
                            gender,
                            age,
                            os
                        FROM 
                            simulator_20231020.feed_actions
                        WHERE 
                            toDate(time) = today() - 1
                        GROUP BY 
                            user_id, 
                            event_date, 
                            gender, 
                            age, 
                            os"""
        df_cube_feed = ph.read_clickhouse(query_feed, connection=connection)
        return df_cube_feed

    # Извлекаем данные по сообщениям
    @task
    def extract_message():
        query_mes = """SELECT event_date, 
                              user_id, 
                              messages_received, 
                              messages_sent, 
                              users_received, 
                              users_sent, 
                              gender, 
                              age, 
                              os
                       FROM
                           (
                           SELECT 
                               toDate(time) as event_date, 
                               user_id,
                               COUNT(DISTINCT receiver_id) as users_sent,
                               COUNT(receiver_id) as messages_sent,
                               gender,
                               age,
                               os
                            FROM 
                                simulator_20231020.message_actions
                            WHERE 
                                toDate(time) = today() - 1
                            GROUP BY 
                                event_date, 
                                user_id, 
                                gender, 
                                age, 
                                os
                            ) as m1
                       FULL OUTER JOIN
                            (
                            SELECT 
                                toDate(time) as event_date, 
                                receiver_id,
                                COUNT(DISTINCT user_id) as users_received,
                                COUNT(user_id) as messages_received,
                                gender,
                                age,
                                os
                            FROM 
                                simulator_20231020.message_actions
                            WHERE 
                                toDate(time) = today() - 1
                            GROUP BY 
                                event_date, 
                                receiver_id, 
                                gender, 
                                age, 
                                os
                            ) as m2
                       ON m1.user_id = m2.receiver_id"""
        df_cube_message = ph.read_clickhouse(query_mes, connection=connection)
        return df_cube_message

    # Объединяем таблицы
    @task
    def merge_tables(df_cube_feed, df_cube_message):
        df_merged_table = df_cube_feed.merge(df_cube_message, 
                                             how='inner', 
                                             on=['user_id', 'event_date', 'gender', 'age', 'os'])
        return df_merged_table
        
    # Формируем срезы по полу, возрасту и операционной системе
    @task
    def transfrom_gender(df_merged_table):
        df_merged_table['dimension'] = 'gender'
        df_cube_gender = df_merged_table[['event_date', 'dimension', 'gender', 'views', 'likes', 'messages_received', 
                                          'messages_sent', 'users_received', 'users_sent']]\
                        .groupby(['event_date', 'dimension', 'gender'])\
                        .sum()\
                        .reset_index()\
                        .rename(columns={'gender': 'dimension_value'})
        return df_cube_gender

    @task
    def transfrom_age(df_merged_table):
        df_merged_table['dimension'] = 'age'
        df_cube_age = df_merged_table[['event_date', 'dimension', 'age', 'views', 'likes', 'messages_received', 
                                       'messages_sent', 'users_received', 'users_sent']]\
                     .groupby(['event_date', 'dimension', 'age'])\
                     .sum()\
                     .reset_index()\
                     .rename(columns={'age': 'dimension_value'})
        return df_cube_age

    @task
    def transfrom_os(df_merged_table):
        df_merged_table['dimension'] = 'os'
        df_cube_os = df_merged_table[['event_date', 'dimension', 'os', 'views', 'likes', 'messages_received', 
                                      'messages_sent', 'users_received', 'users_sent']]\
                     .groupby(['event_date', 'dimension', 'os'])\
                     .sum()\
                     .reset_index()\
                     .rename(columns={'os': 'dimension_value'})
        return df_cube_os
    
    # Сохраняем данные в новую таблицу
    @task
    def load(df_cube_gender, df_cube_age, df_cube_os):
        context = get_current_context()
        ds = context['ds']
        
        final_df = pd.concat([df_cube_gender, df_cube_age, df_cube_os])
        print('Feeds and messages')
        print(final_df.to_csv(index=False, sep='\t'))
        
        query_table = """CREATE TABLE IF NOT EXISTS test.dag_tdemkina(
                            event_date Date, 
                            dimension String, 
                            dimension_value String, 
                            views Int32, 
                            likes Int32, 
                            messages_received Int32, 
                            messages_sent Int32, 
                            users_received Int32, 
                            users_sent Int32
                        ) ENGINE = MergeTree()
                        ORDER BY event_date"""
        table_execute = ph.execute(query=query_table, 
                                   connection=connection_test)
        new_test_table = ph.to_clickhouse(final_df, 
                                          table='dag_tdemkina', 
                                          connection=connection_test, 
                                          index=False)

    df_cube_feed = extract_feed()
    df_cube_message = extract_message()
    df_merged_table = merge_tables(df_cube_feed, df_cube_message)
    
    df_cube_gender = transfrom_gender(df_merged_table)
    df_cube_age = transfrom_age(df_merged_table)
    df_cube_os = transfrom_os(df_merged_table)
    
    load(df_cube_gender, df_cube_age, df_cube_os)

dag_etl_tdemkina = dag_etl_tdemkina()
