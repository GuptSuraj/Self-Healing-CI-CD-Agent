FROM node:22-alpine

WORKDIR /app

COPY apps/dashboard /app

RUN npm install

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
