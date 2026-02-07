# Frontend - Vue.js Ticketing System

A modern, professional Vue.js frontend for the ticketing system with complete authentication, booking flow, and state management.

## Features

### 🔐 Authentication
- User registration and login
- JWT token-based authentication
- Protected routes with navigation guards
- Automatic token refresh handling

### 🎫 Event Management
- Browse available events
- View event details with pricing
- Visual seat availability indicators

### 💺 Booking System
- Interactive seat selection
- Visual seat map with row and seat numbers
- Real-time availability checking
- Multi-step booking flow (Select → Payment → Confirmation)
- Booking summary with pricing

### 📋 Booking History
- View all user bookings
- Booking status tracking (Confirmed, Pending, Cancelled)
- Detailed booking information
- Pagination support

### 🎨 Professional UI/UX
- Modern gradient design
- Responsive layout for all devices
- Reusable component library
- Loading states and error handling
- Smooth animations and transitions

## Project Structure

```
src/
├── components/          # Reusable UI components
│   ├── BaseButton.vue   # Button with loading states
│   ├── BaseCard.vue     # Card container
│   └── BaseInput.vue    # Form input with validation
├── views/               # Page components
│   ├── LoginView.vue    # Authentication page
│   ├── EventsView.vue   # Events listing
│   ├── BookingView.vue  # Booking flow
│   └── BookingsView.vue # Booking history
├── stores/              # Pinia state management
│   ├── auth.js          # Authentication store
│   └── booking.js       # Booking store
├── router/              # Vue Router configuration
│   └── index.js         # Route definitions and guards
├── services/            # API services
│   └── api.js           # Axios client and API methods
├── App.vue              # Root component with navigation
└── main.js              # App initialization
```

## Tech Stack

- **Vue 3** - Progressive JavaScript framework
- **Vue Router** - Official routing library
- **Pinia** - State management
- **Axios** - HTTP client
- **Vite** - Build tool and dev server

## Setup

### Install Dependencies

```bash
cd frontend/vue
npm install
```

### Environment Variables

Copy the `.env.example` file to `.env`:

```bash
cp .env.example .env
```

Configure the API URL:

```env
VITE_API_URL=http://localhost:8000
```

### Development

Start the development server:

```bash
npm run dev
```

The app will be available at http://localhost:5173

### Build for Production

```bash
npm run build
```

The built files will be in the `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

## API Integration

The frontend communicates with the backend through the API Gateway at port 8000.

### API Service Layer

All API calls are centralized in `src/services/api.js`:

- **Authentication API**: Register, login, verify token
- **Booking API**: Get events, reserve seats, capture payment
- **Status API**: Get reservation status, booking details, user bookings

### Authentication Flow

1. User registers or logs in at `/login`
2. JWT token is stored in localStorage
3. Token is automatically added to all API requests via Axios interceptor
4. Protected routes require valid token
5. Invalid/expired tokens redirect to login

### Request/Response Interceptors

- **Request**: Adds JWT token to Authorization header
- **Response**: Handles 401 errors and redirects to login

## State Management

### Auth Store (`stores/auth.js`)

Manages user authentication state:
- Login/Register/Logout actions
- Token verification
- User information
- Loading and error states

### Booking Store (`stores/booking.js`)

Manages booking operations:
- Load event details
- Reserve seats
- Process payments
- Load user bookings
- Reservation state management

## Component Library

### BaseButton

Versatile button component with variants and loading states:

```vue
<BaseButton variant="primary" :loading="isLoading" @click="handleClick">
  Click Me
</BaseButton>
```

Props:
- `variant`: primary, secondary, danger, success
- `loading`: Show loading spinner
- `disabled`: Disable button
- `block`: Full-width button

### BaseInput

Form input with validation and error display:

```vue
<BaseInput
  v-model="email"
  type="email"
  label="Email"
  :error="errors.email"
  required
/>
```

### BaseCard

Card container with header and footer:

```vue
<BaseCard title="Card Title" hover>
  <p>Card content</p>
  <template #footer>
    <BaseButton>Action</BaseButton>
  </template>
</BaseCard>
```

## Routing

### Routes

- `/` - Redirects to `/events`
- `/login` - Authentication page
- `/events` - Browse events (protected)
- `/events/:id` - Book event (protected)
- `/bookings` - View bookings (protected)

### Navigation Guards

Protected routes automatically redirect to login if not authenticated.
Login page redirects to events if already authenticated.

## Booking Flow

### Step 1: Seat Selection

1. Select number of seats
2. Choose preferred row (optional)
3. View visual seat map
4. See booking summary with pricing
5. Click "Reserve Seats"

### Step 2: Payment

1. View reservation confirmation
2. Select payment method (Card/PayPal)
3. Complete payment
4. Payment processed via mock payment service

### Step 3: Confirmation

1. View booking confirmation
2. Display booking ID and details
3. Email notification sent
4. Navigate to bookings or browse more events

## Styling

The app uses a modern, professional design system:

- **Colors**: Purple gradient theme (#667eea to #764ba2)
- **Typography**: System fonts for optimal performance
- **Layout**: Responsive grid and flexbox
- **Animations**: Smooth transitions and hover effects
- **Accessibility**: Proper contrast and focus states

### Responsive Design

- Mobile-first approach
- Breakpoints for tablets and desktops
- Touch-friendly interface
- Collapsible navigation on mobile

## Error Handling

- API errors are caught and displayed to users
- Loading states prevent multiple submissions
- Form validation before submission
- Graceful fallbacks for missing data

## Security

- JWT tokens stored in localStorage
- Tokens sent via Authorization header
- Automatic token expiry handling
- Protected routes require authentication
- No sensitive data in client-side code

## Future Enhancements

- [ ] Real-time seat availability with WebSockets
- [ ] Social login (Google, Facebook)
- [ ] Booking cancellation
- [ ] Email verification
- [ ] Password reset
- [ ] Booking reminders
- [ ] QR code tickets
- [ ] Dark mode
- [ ] Multiple language support
- [ ] Advanced filters for events
- [ ] Calendar integration

## Development Tips

### Hot Module Replacement

Vite provides instant HMR for fast development. Changes to components are reflected immediately without page reload.

### Vue DevTools

Install Vue DevTools browser extension for debugging:
- Inspect component hierarchy
- View store state
- Track events and routing
- Performance profiling

### API Mocking

For offline development, you can mock API responses in the store actions.

### Code Organization

- Keep components small and focused
- Use composables for shared logic
- Store complex state in Pinia stores
- Keep API calls in service layer

## Troubleshooting

### Port Already in Use

If port 5173 is in use, Vite will automatically use the next available port.

### CORS Issues

Ensure the API Gateway has CORS enabled for the frontend origin.

### API Connection Failed

Check that:
1. Backend services are running
2. API Gateway is accessible at port 8000
3. `.env` file has correct API URL

### Build Errors

Clear node_modules and reinstall:

```bash
rm -rf node_modules package-lock.json
npm install
```

## License

MIT License
