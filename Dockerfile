FROM python:3.7

# Add software artifacts
WORKDIR /app
COPY . /app
#ADD requirements.txt .

# Install dependencies
RUN apt-get update && apt-get upgrade -y
RUN apt-get install npm -y
RUN npm install -g newman
RUN pip install -r requirements.txt
RUN pip install .

ARG target

CMD test "$target" = "api" && uvicorn --host 0.0.0.0 --port 8001 mormo.api:app || { test "$target" = "test" &&  pytest || echo -n; }
