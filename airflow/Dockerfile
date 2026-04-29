FROM apache/airflow:2.9.3-python3.11

COPY airflow/requirements-airflow.txt /tmp/requirements-airflow.txt
USER airflow
RUN pip install --no-cache-dir "apache-airflow==2.9.3" -r /tmp/requirements-airflow.txt
