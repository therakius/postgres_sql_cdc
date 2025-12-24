from kafka import KafkaConsumer
import json
from datetime import datetime
import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="transaction_tracking",
    user="postgres",
    password="postgres"
)
conn.autocommit = True
cur = conn.cursor()

consumer = KafkaConsumer(
    'localmysql.transaction_test.fo_feedback_operator',
    bootstrap_servers='localhost:9092',
    auto_offset_reset='earliest',
    group_id='fo_feedback_consumer',
    value_deserializer=lambda m: json.loads(m.decode('utf-8')) if m else None
)

print("Consumidor iniciado...\nAguardando mensagens do kafka")

def upsert_transaction(data):
    try:
        # Converte timestamp para date
        if 'fo_created_on' in data:
            millis = data['fo_created_on']
            created_on = datetime.fromtimestamp(millis / 1000).date()
        else:
            created_on = datetime.now().date()

        # Normaliza strings
        t_code = data["fo_trans_code"].strip()
        t_operator = data["fo_trans_id"].strip()

        # Primeiro tenta atualizar
        cur.execute("""
            UPDATE t_transaction
            SET t_confirmed = TRUE, t_confirmed_on = %s
            WHERE t_code = %s AND t_operator_code = %s
        """, (created_on, t_code, t_operator))

        if cur.rowcount == 0:
            pass
        else:
            print(f"UPDATE → {t_operator} / {t_code}")

    except psycopg2.Error as err:
        print("Erro no PostgreSQL:", err)


# Loop principal do consumidor
for message in consumer:
    if message.value is not None:
        data = message.value
        upsert_transaction(data)
        print("Mensagem processada:", data)
    
    continue
