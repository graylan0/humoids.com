import requests
import os
import openai
import sqlite3
import markdown
import bleach
from waitress import serve
from flask import Flask, render_template, request
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

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
        ''', (sanitize_input(latitude), sanitize_input(longitude),
              sanitize_input(weather_insights),
              sanitize_input(location_suggestions), datetime.now()))
  conn.commit()
  conn.close()


def retrieve_from_sql(latitude, longitude):
  conn = sqlite3.connect('weather_data.db')
  cursor = conn.cursor()
  cursor.execute(
    'SELECT weather_insights, location_suggestions, timestamp FROM weather WHERE latitude = ? AND longitude = ?',
    (latitude, longitude))  # Removed sanitize_input calls
  result = cursor.fetchone()
  conn.close()
  return result if result else (None, None, None)


def get_weather_insights(latitude, longitude):

  def fetch_weather_data():
    url = f'https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=temperature_2m,soil_moisture_0_1cm&temperature_unit=fahrenheit&forecast_days=16'
    response = requests.get(url)
    return response.json() if response.status_code == 200 else None

  with ThreadPoolExecutor() as executor:
    future = executor.submit(fetch_weather_data)
    weather_data = future.result()

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
  latitude = request.form.get('latitude', '34.8298')
  longitude = request.form.get('longitude', '-82.6015')

  # Validate that latitude and longitude are valid floating-point numbers
  try:
    latitude = float(latitude)
    longitude = float(longitude)
  except ValueError:
    # Handle the error, e.g., return an error message or redirect to an error page
    return "Invalid latitude or longitude"

  # Ensure latitude and longitude are within valid ranges
  if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
    return "Invalid latitude or longitude"

  weather_insights, location_suggestions, timestamp = retrieve_from_sql(
    latitude, longitude)

  if timestamp is None or (datetime.now() -
                           datetime.fromisoformat(timestamp)) > timedelta(
                             hours=24):
    weather_insights = get_weather_insights(latitude, longitude)
    location_suggestions = get_location_suggestions(weather_insights, latitude,
                                                    longitude)
    save_to_sql(latitude, longitude, weather_insights, location_suggestions)

  weather_insights_html = markdown.markdown(weather_insights)
  location_suggestions_html = markdown.markdown(location_suggestions)

  return render_template('weather.html',
                         weather_insights=weather_insights_html,
                         location_suggestions=location_suggestions_html)


def create_app():
  app = Flask(__name__)
  app.route('/', methods=['GET', 'POST'])(weather)
  return app


if __name__ == '__main__':
  initialize_db()
  app = create_app()
  serve(app, host='0.0.0.0', port=8080)
