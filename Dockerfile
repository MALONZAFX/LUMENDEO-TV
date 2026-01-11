FROM python:3.10-alpine

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DEBUG 0

# Set work directory
WORKDIR /app

# Install dependencies
COPY ./requirements.txt .



RUN pip install --upgrade pip

RUN pip install --upgrade setuptools

RUN pip install gunicorn
RUN pip install Pillow
RUN pip install python-dotenv
RUN pip install django-storages[boto3]
RUN pip install django-pwa









RUN pip install intasend-python

# Copy project
COPY . .
RUN pip install -r requirements.txt

# Make migrations
#



EXPOSE 8080
#CMD python manage.py migrate notifications 

CMD  python manage.py makemigrations &&  python manage.py migrate && gunicorn dict.wsgi:application --bind 0.0.0.0:$PORT