import requests
import os
import openai
import sqlite3
import bleach
from flask import Flask, render_template, request
from datetime import datetime, timedelta

openai_api_key = os.environ.get('OPENAI_API_KEY')

if openai_api_key is None:
  raise Exception("OPENAI_API_KEY environment variable is not set")

openai.api_key = openai_api_key  # Set the OpenAI API key


def sanitize_input(input_text):
    allowed_tags = []  # No HTML tags allowed
    return bleach.clean(input_text, tags=allowed_tags)


def initialize_db():
    conn = sqlite3.connect('weather_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS weather (
            latitude REAL,
            longitude REAL,
            weather_insights TEXT,
            location_suggestions TEXT,
            timestamp DATETIME,
            PRIMARY KEY (latitude, longitude)
        )
    ''')
    conn.commit()
    conn.close()


def save_to_sql(latitude, longitude, weather_insights, location_suggestions):
    conn = sqlite3.connect('weather_data.db')
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT OR REPLACE INTO weather (latitude, longitude, weather_insights, location_suggestions, timestamp)
        VALUES (?, ?, ?, ?, ?)
        ''', (sanitize_input(latitude), sanitize_input(longitude), sanitize_input(weather_insights),
              sanitize_input(location_suggestions), datetime.now()))
    conn.commit()
    conn.close()


def retrieve_from_sql(latitude, longitude):
    conn = sqlite3.connect('weather_data.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT weather_insights, location_suggestions, timestamp FROM weather WHERE latitude = ? AND longitude = ?',
        (sanitize_input(latitude), sanitize_input(longitude)))
    result = cursor.fetchone()
    conn.close()
    return result if result else (None, None, None)


def get_weather_insights(latitude, longitude):
  url = f'https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=temperature_2m,soil_moisture_0_1cm&temperature_unit=fahrenheit&forecast_days=16'
  response = requests.get(url)
  weather_data = response.json() if response.status_code == 200 else None

  # Check if weather_data is None and handle the error
  if weather_data is None:
    return "Error fetching weather data"

  rules = f"""Analyze the weather data for the given location with the following details:
                Temperature: {weather_data['hourly']['temperature_2m']},
                Timestamps: {datetime.now().strftime("%Y-%m-%d %H:%M")} to {datetime.now() + timedelta(hours=len(weather_data['hourly']['temperature_2m']) - 1)}. Provide insights and predictions."""

  response = openai.ChatCompletion.create(
    model='gpt-3.5-turbo',
    messages=[{
      "role": "system",
      "content": rules
    }, {
      "role":
      "user",
      "content":
      "Please analyze the weather data and provide insights."
    }],
  )
  return response['choices'][0]['message']['content']


def get_location_suggestions(weather_insights, latitude, longitude):
  prompt = f"The weather insights for the location (Latitude: {latitude}, Longitude: {longitude}) are as follows: {weather_insights}. Suggest the best locations and activities for a day out in this area."
  response = openai.ChatCompletion.create(model='gpt-3.5-turbo',
                                          messages=[{
                                            "role":
                                            "system",
                                            "content":
                                            "You are a helpful assistant."
                                          }, {
                                            "role": "user",
                                            "content": prompt
                                          }],
                                          max_tokens=150)
  return response['choices'][0]['message']['content']


def update_easley_sc():
  latitude = '34.8298'
  longitude = '-82.6015'
  weather_insights = get_weather_insights(latitude, longitude)
  location_suggestions = get_location_suggestions(weather_insights, latitude,
                                                  longitude)
  save_to_sql(latitude, longitude, weather_insights, location_suggestions)


def weather():
  latitude = request.form.get('latitude',
                              '34.8298')  # Default latitude for Easley, SC
  longitude = request.form.get('longitude',
                               '-82.6015')  # Default longitude for Easley, SC

  # Retrieve from database
  weather_insights, location_suggestions, timestamp = retrieve_from_sql(
    latitude, longitude)

  # Check if data is older than 24 hours or if it's the default location
  if timestamp is None or (datetime.now() -
                           datetime.fromisoformat(timestamp)) > timedelta(
                             hours=24):
    weather_insights = get_weather_insights(latitude, longitude)
    location_suggestions = get_location_suggestions(
      weather_insights, latitude, longitude)  # Corrected line
    save_to_sql(latitude, longitude, weather_insights, location_suggestions)

  return render_template('weather.html',
                         weather_insights=weather_insights,
                         location_suggestions=location_suggestions)


def create_app():
  app = Flask(__name__)

  app.route('/',
            methods=['GET', 'POST'
                     ])(weather)  # Register the weather function as a route

  return app  # Return the app object


if __name__ == '__main__':
    initialize_db()
    app = create_app()
    app.run(host='0.0.0.0', port=8080, debug=False)
