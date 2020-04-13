FROM python:3.7

WORKDIR /app

RUN apt-get update\
  && apt-get upgrade -y\
  && apt-get install npm -y\
  && npm install -g newman@5.0.0

COPY requirements.txt /app
RUN pip install -r requirements.txt

ARG target
RUN test "$target" = "test" && pip install pytest || { test "$target" != "test" && return 0; }

COPY . /app
RUN pip install .

CMD uvicorn --host 0.0.0.0 --port 8001 mormo.api:app
