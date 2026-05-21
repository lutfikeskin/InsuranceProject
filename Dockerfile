# Use an official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.11-slim

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

# Install production dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Run the web service on container startup with the HTMX shell.
# For environments with multiple CPU cores, increase workers via a real WSGI server as needed.
CMD flask --app webapp.app run --host 0.0.0.0 --port 8080
