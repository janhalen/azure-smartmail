# Pull a pre-built  docker image with keras, TF, nginx, python3 installed
# partly based on https://medium.com/@joelognn/serving-and-deploying-keras-models-using-flask-uwsgi-nginx-and-docker-810fa1864cec
# see also: https://code.visualstudio.com/docs/python/tutorial-deploy-containers
FROM tensorflow/tensorflow:2.1.0-py3

#ARG env=d
#ARG customer_id=1

#ENV ENV ${env}
#ENV CUSTOMER_ID ${customer_id}
#EXPOSE 5000

# get necessary https driver for apt
RUN apt-get update
RUN apt-get install -y apt-transport-https curl

## ms sql stuff: https://docs.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server?view=sql-server-2017
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
RUN curl https://packages.microsoft.com/config/ubuntu/18.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
RUN apt-get update
RUN ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev mssql-tools

# Install Java - used by the pdf parser 
RUN apt-get install -y default-jre

# see ENV description here: https://github.com/chrismattmann/tika-python/blob/master/README.md
# a directory with write permissions and the tika_server.jar file will be placed in this directory.
#ENV TIKA_PATH /app/tika
# tika server jar
#ENV TIKA_SERVER_JAR /app/tika/tika-server-1.19.jar
# On azure the tika server is slow to start
#ENV TIKA_STARTUP_MAX_RETRY 6

# Define commonly used JAVA_HOME variable
#ENV JAVA_HOME /usr/lib/jvm/java-8-oracle

# Install python dependencies
COPY requirements.txt /

#RUN pip install --no-cache-dir -U pip
RUN pip install --no-cache-dir -r /requirements.txt

COPY ./mailjournalisering /mailjournalisering

CMD ["python", "-u", "/mailjournalisering/main.py"]