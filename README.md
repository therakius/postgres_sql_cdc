# Documentação: Sincronização MySQL → PostgreSQL via Kafka/Debezium

## 1. Visão Geral

Este documento descreve o processo de implementação de uma sincronização em tempo real entre duas bases de dados em servidores diferentes:
- **Origem**: MySQL (local)
- **Destino**: PostgreSQL (remoto)
- **Tecnologias**: Kafka, Debezium, Zookeeper, Docker

### Arquitetura

```
MySQL (local) → Debezium → Kafka → Consumer Python → PostgreSQL (remoto)
```

## 2. Pré-requisitos

Antes de começar, certifica-te que tens instalado:

- Docker e Docker Compose
- Python 3.x
- MySQL com acesso de administrador
- PostgreSQL com acesso de administrador

### Bibliotecas Python necessárias

```bash
pip install kafka-python psycopg2-binary
```

## 3. Estrutura do Projeto

```
project/
├── docker-compose.yaml
├── connector.json
└── sync_pg.py
```

## 4. Implementação Passo a Passo

### 4.1. Configurar o MySQL

#### 4.1.1. Ativar o Binary Log

O Debezium precisa do binlog do MySQL para capturar mudanças. Edita o ficheiro de configuração do MySQL:

**Linux**: `/etc/mysql/my.cnf` ou `/etc/mysql/mysql.conf.d/mysqld.cnf`  
**Windows**: `C:\ProgramData\MySQL\MySQL Server X.X\my.ini`

Adiciona as seguintes linhas na secção `[mysqld]`:

```ini
[mysqld]
server-id = 1
log_bin = mysql-bin
binlog_format = ROW
binlog_row_image = FULL
expire_logs_days = 10
```

#### 4.1.2. Reiniciar o MySQL

```bash
# Linux
sudo systemctl restart mysql

# ou
sudo service mysql restart

# Windows
net stop MySQL
net start MySQL
```

#### 4.1.3. Verificar se o binlog está ativo

```sql
SHOW VARIABLES LIKE 'log_bin';
```

Resultado esperado: `log_bin = ON`

#### 4.1.4. Criar utilizador para o Debezium

```sql
CREATE USER 'dbuser'@'%' IDENTIFIED BY 'password';

GRANT SELECT, RELOAD, SHOW DATABASES, REPLICATION SLAVE, REPLICATION CLIENT 
ON *.* TO 'dbuser'@'%';

FLUSH PRIVILEGES;
```

#### 4.1.5. Testar a conexão

```bash
mysql -h 172.17.0.1 -u dbuser -p
```

### 4.2. Configurar o PostgreSQL

#### 4.2.1. Criar a base de dados de destino

```sql
CREATE DATABASE transaction_tracking;
```

#### 4.2.2. Conectar à base de dados

```sql
\c transaction_tracking
```

#### 4.2.3. Criar a tabela de destino

```sql
CREATE TABLE t_transaction (
    id SERIAL PRIMARY KEY,
    t_code VARCHAR(255) NOT NULL,
    t_operator_code VARCHAR(255) NOT NULL,
    t_confirmed BOOLEAN DEFAULT FALSE,
    t_confirmed_on DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(t_code, t_operator_code)
);

-- Índices para melhor performance
CREATE INDEX idx_t_code ON t_transaction(t_code);
CREATE INDEX idx_t_operator_code ON t_transaction(t_operator_code);
```

### 4.3. Configurar o Docker Compose

#### 4.3.1. Criar o ficheiro `docker-compose.yaml`

```yaml
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:5.5.3
    container_name: zookeeper
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000

  kafka:
    image: confluentinc/cp-enterprise-kafka:5.5.3
    container_name: kafka
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
    environment:
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:29092,PLAINTEXT_HOST://0.0.0.0:9092
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_BROKER_ID: 1
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"

  connect:
    image: debezium/connect:1.4
    container_name: debezium-connect
    depends_on:
      - kafka
    ports:
      - "8083:8083"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      BOOTSTRAP_SERVERS: kafka:29092
      GROUP_ID: 1
      CONFIG_STORAGE_TOPIC: connect-configs
      OFFSET_STORAGE_TOPIC: connect-offsets
      STATUS_STORAGE_TOPIC: connect-status
      
      KEY_CONVERTER: org.apache.kafka.connect.storage.StringConverter
      VALUE_CONVERTER: org.apache.kafka.connect.json.JsonConverter
      CONNECT_VALUE_CONVERTER_SCHEMAS_ENABLE: "false"
      
      CONNECT_REST_HOST_NAME: 0.0.0.0
      CONNECT_REST_ADVERTISED_HOST_NAME: localhost
      CONNECT_REST_PORT: 8083
```

#### 4.3.2. Iniciar os containers

```bash
docker-compose up -d
```

#### 4.3.3. Verificar o estado dos containers

```bash
docker ps
```

Resultado esperado: 3 containers em estado "Up"

```
CONTAINER ID   IMAGE                                    STATUS
abc123...      debezium/connect:1.4                     Up
def456...      confluentinc/cp-enterprise-kafka:5.5.3   Up
ghi789...      confluentinc/cp-zookeeper:5.5.3          Up
```

#### 4.3.4. Verificar logs (opcional)

```bash
# Kafka
docker logs kafka

# Debezium
docker logs debezium-connect

# Zookeeper
docker logs zookeeper
```

Depois de 15-20s, execute:

```bash
    curl http://localhost:8083
```

Se testiver tudo certo, tera um json semelhante ao json abaixo, como resposta:

```json
    {"version":"2.6.1","commit":"6b2021cd52659cef","kafka_cluster_id":"sW2FrpvbTxilnTOEGJjSdw"}
```


### 4.4. Configurar o Conector Debezium

#### 4.4.1. Criar o ficheiro `connector.json`

**Importante**: Substitui os seguintes valores pelos teus dados reais:
- `database.port`: porta do MySQL (normalmente 3306)
- `database.user`: utilizador criado anteriormente
- `database.password`: senha do utilizador
- `database.include.list`: nome da base de dados MySQL
- `table.include.list`: formato `database.table`

```json
{
  "name": "mysql-fo-feedback-connector",
  "config": {
    "connector.class": "io.debezium.connector.mysql.MySqlConnector",
    "tasks.max": "1",
    "database.hostname": "172.17.0.1",
    "database.port": "3306",
    "database.user": "dbuser",
    "database.password": "password",
    "database.server.id": "666",
    "database.server.name": "localmysql",
    "database.include.list": "transaction_test",
    "table.include.list": "transaction_test.fo_feedback_operator",
    "database.history.kafka.bootstrap.servers": "kafka:29092",
    "database.history.kafka.topic": "dbhistory.fo_feedback_operator",
    "database.allowPublicKeyRetrieval": "true",
    "key.converter": "org.apache.kafka.connect.storage.StringConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.schemas.enable": "false",
    "transforms": "unwrap",
    "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
    "transforms.unwrap.drop.tombstones": "false"
  }
}
```

#### 4.4.2. Registar o conector no Debezium

```bash
curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" \
http://localhost:8083/connectors/ -d @connector.json
```

Resposta esperada:

```
HTTP/1.1 201 Created
...
```

#### 4.4.3. Verificar o estado do conector

```bash
# Listar todos os conectores
curl http://localhost:8083/connectors/

# Ver detalhes do conector específico
curl http://localhost:8083/connectors/mysql-fo-connector/status
```

Resposta esperada (status RUNNING):

```json
{
  "name": "mysql-fo-connector",
  "connector": {
    "state": "RUNNING",
    "worker_id": "connect:8083"
  },
  "tasks": [
    {
      "id": 0,
      "state": "RUNNING",
      "worker_id": "connect:8083"
    }
  ]
}
```

#### 4.4.4. Verificar tópicos criados no Kafka

```bash
docker exec -it kafka kafka-topics --list --bootstrap-server localhost:29092
```

Deves ver um tópico com o formato: `localmysql.transaction_test.fo_feedback_operator`

### 4.5. Implementar o Consumer Python

#### 4.5.1. Criar o ficheiro `sync_pg.py`

**Importante**: Ajusta as credenciais do PostgreSQL e o nome do tópico Kafka.

```python
from kafka import KafkaConsumer
import json
from datetime import datetime
import psycopg2

# Conexão ao PostgreSQL
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="transaction_tracking",
    user="postgres",
    password="postgres"
)
conn.autocommit = True
cur = conn.cursor()

# Configuração do consumidor Kafka
consumer = KafkaConsumer(
    'localmysql.transaction_test.fo_feedback_operator',
    bootstrap_servers='localhost:9092',
    auto_offset_reset='earliest',
    group_id='fo_feedback_consumer',
    value_deserializer=lambda m: json.loads(m.decode('utf-8'))
)

print("Consumidor iniciado... Aguardando mensagens do Kafka")

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

        # Tenta atualizar
        cur.execute("""
            UPDATE t_transaction
            SET t_confirmed = TRUE, t_confirmed_on = %s
            WHERE t_code = %s AND t_operator_code = %s
        """, (created_on, t_code, t_operator))

        if cur.rowcount == 0:
            print(f"SKIP → Registo não encontrado: {t_operator} / {t_code}")
        else:
            print(f"UPDATE → {t_operator} / {t_code}")

    except psycopg2.Error as err:
        print("Erro no PostgreSQL:", err)

# Loop principal do consumidor
for message in consumer:
    data = message.value
    upsert_transaction(data)
    print("Mensagem processada:", data)
```

#### 4.5.2. Executar o consumer

```bash
python sync_pg.py
```

Saída esperada:

```
Consumidor iniciado... 
Aguardando mensagens do Kafka
```

## 5. Testar a Sincronização

### 5.1. Inserir dados no MySQL

```sql
USE transaction_test;

INSERT INTO fo_feedback_operator (fo_trans_code, fo_trans_id, fo_created_on)
VALUES ('TRX001', 'OP123', UNIX_TIMESTAMP() * 1000);
```

### 5.2. Verificar o consumer Python

No terminal onde o `sync_pg.py` está a correr, deves ver:

```
Mensagem processada: {'fo_trans_code': 'TRX001', 'fo_trans_id': 'OP123', ...}
UPDATE → OP123 / TRX001
```

### 5.3. Verificar o PostgreSQL

```sql
SELECT * FROM t_transaction WHERE t_code = 'TRX001';
```

Resultado esperado:

```
 id | t_code  | t_operator_code | t_confirmed | t_confirmed_on
----+---------+-----------------+-------------+----------------
  1 | TRX001  | OP123           | t           | 2024-12-24
```

## 6. Monitorização

### 6.1. Ver mensagens no tópico Kafka

```bash
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:29092 \
  --topic localmysql.transaction_test.fo_feedback_operator \
  --from-beginning
```

### 6.2. Verificar logs dos containers

```bash
# Kafka
docker logs -f kafka

# Debezium
docker logs -f debezium-connect

# Zookeeper
docker logs -f zookeeper
```

### 6.3. Status do conector

```bash
curl http://localhost:8083/connectors/mysql-fo-feedback-connector/status | json_pp
```

## 7. Troubleshooting

### Problema 1: Conector não consegue conectar ao MySQL

**Sintoma**: Status do conector é `FAILED`

**Soluções**:

1. Verifica se o binlog está ativo:
   ```sql
   SHOW VARIABLES LIKE 'log_bin';
   ```

2. Verifica as permissões do utilizador:
   ```sql
   SHOW GRANTS FOR 'dbuser'@'%';
   ```

3. Testa a conexão manualmente:
   ```bash
   mysql -h 172.17.0.1 -u dbuser -p
   ```

4. Verifica o IP correto do host:
   ```bash
   # No Linux, IP da bridge Docker
   ip addr show docker0
   
   # Testa a conexão desde o container
   docker exec -it debezium-connect ping 172.17.0.1
   ```

### Problema 2: Consumer não recebe mensagens

**Soluções**:

1. Verifica se o tópico existe:
   ```bash
   docker exec -it kafka kafka-topics --list --bootstrap-server localhost:29092
   ```

2. Confirma o nome do tópico no Python (formato: `{server.name}.{database}.{table}`)

3. Testa se há mensagens no tópico:
   ```bash
   docker exec -it kafka kafka-console-consumer \
     --bootstrap-server localhost:29092 \
     --topic localmysql.transaction_test.fo_feedback_operator \
     --from-beginning
   ```

### Problema 3: Erro de conexão ao PostgreSQL

**Sintoma**: `psycopg2.OperationalError`

**Soluções**:

1. Verifica se o PostgreSQL está a correr:
   ```bash
   sudo systemctl status postgresql
   ```

2. Testa a conexão manualmente:
   ```bash
   psql -h localhost -U postgres -d transaction_tracking
   ```

3. Verifica se o utilizador tem permissões:
   ```sql
   GRANT ALL PRIVILEGES ON DATABASE transaction_tracking TO postgres;
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
   ```

### Problema 4: Containers não iniciam

**Soluções**:

1. Verifica portas em uso:
   ```bash
   # Linux/Mac
   sudo netstat -tulpn | grep -E '2181|9092|8083'
   
   # Windows
   netstat -ano | findstr "2181 9092 8083"
   ```

2. Remove containers antigos:
   ```bash
   docker-compose down -v
   docker-compose up -d
   ```

3. Limpa volumes Docker:
   ```bash
   docker volume prune
   ```

## 8. Comandos Úteis

### Gestão de containers

```bash
# Iniciar
docker-compose up -d

# Parar
docker-compose stop

# Reiniciar
docker-compose restart

# Remover (com volumes)
docker-compose down -v

# Ver logs em tempo real
docker-compose logs -f
```

### Gestão do conector

```bash
# Listar conectores
curl http://localhost:8083/connectors/

# Ver configuração
curl http://localhost:8083/connectors/mysql-fo-feedback-connector

# Pausar conector
curl -X PUT http://localhost:8083/connectors/mysql-fo-feedback-connector/pause

# Retomar conector
curl -X PUT http://localhost:8083/connectors/mysql-fo-feedback-connector/resume

# Reiniciar conector
curl -X POST http://localhost:8083/connectors/mysql-fo-feedback-connector/restart

# Remover conector
curl -X DELETE http://localhost:8083/connectors/mysql-fo-feedback-connector
```

### Kafka

```bash
# Listar tópicos
docker exec -it kafka kafka-topics --list --bootstrap-server localhost:29092

# Descrever tópico
docker exec -it kafka kafka-topics --describe \
  --topic localmysql.transaction_test.fo_feedback_operator \
  --bootstrap-server localhost:29092

# Ver mensagens desde o início
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:29092 \
  --topic localmysql.transaction_test.fo_feedback_operator \
  --from-beginning

# Ver consumer groups
docker exec -it kafka kafka-consumer-groups --list --bootstrap-server localhost:29092

# Detalhes do consumer group
docker exec -it kafka kafka-consumer-groups --describe \
  --group fo_feedback_consumer \
  --bootstrap-server localhost:29092
```

## 10. Referências

- [Debezium Documentation](https://debezium.io/documentation/)
- [Kafka Documentation](https://kafka.apache.org/documentation/)
- [MySQL Binary Log](https://dev.mysql.com/doc/refman/8.0/en/binary-log.html)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [iritza07 repo](https://github.com/irtiza07/postgres_debezium_cdc)

---

**Última atualização**: Dezembro 2025  
**Versão**: 1.0