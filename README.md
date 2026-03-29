# WHASABI - AI Receptionist Landing Page Chat

WHASABI is a minimal AI-powered landing page chat system for small businesses in Mexico. It allows visitors to chat with an AI assistant that acts like a receptionist, answers questions, and automatically captures leads (name, phone, intent).

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion
- **Backend**: FastAPI (Python)
- **Database**: MongoDB (Motor)
- **AI Provider**: DeepSeek API

## Project Structure
- `/backend`: FastAPI backend
- `/frontend`: React frontend

---

## 🚀 Environment Variables

Create a `.env` file in the **`/backend`** folder:
```env
MONGO_URL=mongodb+srv://<user>:<password>@cluster.mongodb.net/
DB_NAME=whasabi_db
DEEPSEEK_API_KEY=sk-...
CORS_ORIGINS=https://your-frontend.netlify.app,http://localhost:3000
PORT=8001
```

Create a `.env` file in the **`/frontend`** folder:
```env
REACT_APP_BACKEND_URL=https://your-backend.onrender.com
```

---

## 🛠️ Local Development

### 1. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python server.py
# Or run with uvicorn: uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### 2. Frontend
```bash
cd frontend
yarn install
yarn start
```

---

## 🌐 Production Deployment Guide

The application is structured to be easily deployed on **Netlify** (Frontend) and **Render** (Backend).

### Deploy Backend to Render

1. Go to [Render](https://render.com) and create a new **Web Service**.
2. Connect your GitHub repository.
3. Set the **Root Directory** to `backend`.
4. Environment: `Python`
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
7. Add the required Environment Variables listed above (make sure `CORS_ORIGINS` includes your future Netlify URL).
8. Deploy!

### Database: Connect MongoDB Atlas
1. Create a free cluster on [MongoDB Atlas](https://www.mongodb.com/cloud/atlas).
2. Get your connection string (URI).
3. Add the `MONGO_URL` and `DB_NAME` to your Render environment variables.

### Deploy Frontend to Netlify

1. Go to [Netlify](https://www.netlify.com) and add a new site from GitHub.
2. Set the **Base directory** to `frontend`.
3. Build command: `yarn build`
4. Publish directory: `frontend/build`
5. Add the Environment Variable:
   - `REACT_APP_BACKEND_URL` = `https://your-backend.onrender.com` (The URL provided by Render)
6. Deploy!
*(Note: A `public/_redirects` file is already included to support React Router client-side routing on Netlify).*

---

## 📱 Features

- **Dynamic Routing**: Visit `/cafe-minima` or `/dentista-lopez` to see different business profiles.
- **Admin Dashboard**: Visit `/admin/cafe-minima` (Password: `1234`) to view captured leads.
- **Lead Capture**: Automatically extracts Name, Phone (10 digits), and Intent from natural Spanish conversation without forms.
