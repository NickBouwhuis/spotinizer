FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the rest of the application
COPY . .

# Create directory for Streamlit config
RUN mkdir -p /root/.streamlit

# Expose Streamlit port
EXPOSE 8501

# Command to run the application
CMD ["streamlit", "run", "spotify_organizer.py"]
