FROM registry.access.redhat.com/ubi9/python-311:latest

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 8080

CMD ["python", "app.py"]
