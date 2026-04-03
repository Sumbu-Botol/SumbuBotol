FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN mkdir -p uploads results

EXPOSE 8000
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
