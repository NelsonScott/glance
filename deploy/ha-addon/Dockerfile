FROM python:3.12-slim
WORKDIR /app
COPY requirements-lite.txt .
RUN pip install --no-cache-dir -r requirements-lite.txt
COPY feed_server.py providers.py nitehawk.py comedy_lite.py run.sh ./
COPY webapp ./webapp
RUN chmod +x run.sh
EXPOSE 8090
CMD ["/app/run.sh"]
