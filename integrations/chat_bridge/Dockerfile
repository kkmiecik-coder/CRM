FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Kopiujemy CAŁY pakiet (core/, channels/, panels/, *.py) — importy absolutne rootowane w /app.
COPY . /app
EXPOSE 5005
CMD ["python", "bridge.py"]
