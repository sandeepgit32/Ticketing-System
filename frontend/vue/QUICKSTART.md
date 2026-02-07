# Quick Start Guide - Frontend

## 🚀 Get Started in 3 Steps

### 1. Install Dependencies
```bash
cd frontend/vue
npm install
```

### 2. Start Development Server
```bash
npm run dev
```

### 3. Open Browser
Navigate to **http://localhost:5173**

---

## 📱 Using the Application

### First Time Setup
1. **Register**: Create a new account with email and password
2. **Login**: Sign in with your credentials

### Booking Flow
1. **Browse Events**: View available events on the home page
2. **Select Event**: Click "Book Now" on any event
3. **Choose Seats**: 
   - Select number of seats
   - Pick preferred row (optional)
   - View visual seat map
4. **Reserve**: Click "Reserve Seats"
5. **Payment**: Choose payment method and pay
6. **Confirmation**: Get booking confirmation with ticket details

### View Bookings
- Click "My Bookings" in the navigation
- See all your past and upcoming bookings
- Download tickets (confirmed bookings)

---

## 🎨 Features

✅ **Authentication** - Secure login/register with JWT  
✅ **Event Browsing** - Beautiful grid layout of events  
✅ **Interactive Seat Map** - Visual seat selection  
✅ **Multi-step Booking** - Guided booking process  
✅ **Payment Processing** - Mock payment integration  
✅ **Booking History** - Track all your bookings  
✅ **Responsive Design** - Works on all devices  
✅ **Loading States** - Clear feedback on actions  
✅ **Error Handling** - Graceful error messages  

---

## 🔧 Configuration

### Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Default configuration:
```env
VITE_API_URL=http://localhost:8000
```

### Backend Connection
Make sure the backend services are running:
```bash
# From project root
docker compose up
```

---

## 📁 Project Structure

```
src/
├── components/          # Reusable UI components
│   ├── BaseButton.vue   # Versatile button
│   ├── BaseCard.vue     # Card container
│   └── BaseInput.vue    # Form input
├── views/               # Page components
│   ├── LoginView.vue    # Login/Register page
│   ├── EventsView.vue   # Events listing
│   ├── BookingView.vue  # Booking flow
│   └── BookingsView.vue # Booking history
├── stores/              # State management
│   ├── auth.js          # Authentication
│   └── booking.js       # Booking operations
├── router/              # Routing
│   └── index.js         # Route configuration
└── services/            # API layer
    └── api.js           # API client
```

---

## 🛠️ Available Commands

```bash
# Development
npm run dev          # Start dev server

# Production
npm run build        # Build for production
npm run preview      # Preview production build
```

---

## 🐛 Troubleshooting

### Port Already in Use
Vite will automatically use the next available port. Check the terminal output for the actual port.

### API Connection Failed
- Verify backend is running: `docker compose ps`
- Check API URL in `.env` file
- Ensure API Gateway is at port 8000

### Login Not Working
- Check browser console for errors
- Verify backend auth service is running
- Clear localStorage and try again

### Build Errors
```bash
# Clean and reinstall
rm -rf node_modules package-lock.json
npm install
```

---

## 📚 Learn More

- [Frontend README](README.md) - Complete documentation
- [Refactoring Summary](../REFACTORING_SUMMARY.md) - What changed
- [API Documentation](../../API_DOCS.md) - Backend API reference
- [Architecture](../../ARCHITECTURE.md) - System architecture

---

## 💡 Tips

- Use **Vue DevTools** browser extension for debugging
- Check **Network tab** in browser DevTools for API calls
- Use **Console** to see any JavaScript errors
- **Responsive design** - Try different screen sizes
- **Authentication** is required for booking operations

---

## 🎯 Testing Checklist

- [ ] Register new user
- [ ] Login with credentials
- [ ] Browse events
- [ ] Select and view event details
- [ ] Reserve seats
- [ ] Complete payment
- [ ] View confirmation
- [ ] Check booking history
- [ ] Logout and login again
- [ ] Test on mobile device

---

## 🚀 Production Deployment

```bash
# Build optimized bundle
npm run build

# The dist/ folder contains production files
# Deploy to any static hosting:
# - Netlify
# - Vercel
# - AWS S3 + CloudFront
# - GitHub Pages
```

### Environment Variables for Production
```env
VITE_API_URL=https://your-api-domain.com
```

---

## 📞 Support

Having issues? Check:
1. Terminal for error messages
2. Browser console for JavaScript errors
3. Network tab for failed API requests
4. Backend logs: `docker compose logs -f`

---

**Happy Coding! 🎉**
