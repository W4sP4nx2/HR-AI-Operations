# Frontend image for the HR AI Command Center Next.js app.
FROM node:20-alpine

WORKDIR /app

# Install dependencies first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the application.
COPY . .

EXPOSE 3000

# In development docker-compose overrides this with `npm run dev`.
CMD ["npm", "run", "dev"]
