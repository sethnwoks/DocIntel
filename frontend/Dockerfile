FROM node:20-alpine

WORKDIR /app

# Copy package.json to install dependencies
COPY package.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application files
COPY . .

# Expose port 3000 for the Next.js dev server
EXPOSE 3000

# Start the dev server
CMD ["npm", "run", "dev"]
