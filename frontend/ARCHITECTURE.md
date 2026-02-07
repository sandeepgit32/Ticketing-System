# Frontend Architecture Diagram

## Component Hierarchy

```
App.vue (Root)
├── Navigation Bar (authenticated users only)
│   ├── Brand Logo & Link
│   ├── Nav Menu
│   │   ├── Events Link
│   │   └── My Bookings Link
│   └── User Section
│       ├── User Email
│       └── Logout Button
│
└── Router View (main content)
    │
    ├── LoginView (/)
    │   └── BaseCard
    │       ├── Form
    │       │   ├── BaseInput (email)
    │       │   ├── BaseInput (password)
    │       │   ├── BaseInput (full_name - register only)
    │       │   └── BaseButton (submit)
    │       └── Toggle Login/Register
    │
    ├── EventsView (/events)
    │   ├── Header Section
    │   └── Events Grid
    │       └── BaseCard (for each event)
    │           ├── Event Image
    │           ├── Event Details
    │           └── BaseButton (Book Now)
    │
    ├── BookingView (/events/:id)
    │   ├── Back Button
    │   ├── Event Title
    │   └── Multi-Step Flow
    │       │
    │       ├── Step 1: Seat Selection
    │       │   └── BaseCard
    │       │       ├── Selection Controls
    │       │       │   ├── Number of Seats Dropdown
    │       │       │   └── Preferred Row Dropdown
    │       │       ├── Visual Seat Map
    │       │       │   ├── Stage Display
    │       │       │   ├── Seat Rows (A-F)
    │       │       │   └── Legend
    │       │       ├── Booking Summary
    │       │       └── BaseButton (Reserve)
    │       │
    │       ├── Step 2: Payment
    │       │   └── BaseCard
    │       │       ├── Success Icon
    │       │       ├── Reservation Details
    │       │       ├── Payment Method Selection
    │       │       │   ├── Card Option
    │       │       │   └── PayPal Option
    │       │       └── Action Buttons
    │       │           ├── BaseButton (Cancel)
    │       │           └── BaseButton (Pay Now)
    │       │
    │       └── Step 3: Confirmation
    │           └── BaseCard
    │               ├── Confirmation Icon
    │               ├── Booking Details
    │               └── Action Buttons
    │                   ├── BaseButton (View Bookings)
    │                   └── BaseButton (Book More)
    │
    └── BookingsView (/bookings)
        ├── Header Section
        └── Bookings List
            ├── BaseCard (for each booking)
            │   ├── Booking Header
            │   │   ├── Event Name
            │   │   └── Status Badge
            │   ├── Booking Details
            │   └── Action Buttons
            │       ├── BaseButton (View Details)
            │       └── BaseButton (Download Ticket)
            │
            └── BaseButton (Load More)
```

## State Management Flow

```
Pinia Stores
│
├── Auth Store
│   ├── State
│   │   ├── token
│   │   ├── user
│   │   ├── loading
│   │   └── error
│   │
│   └── Actions
│       ├── login()
│       ├── register()
│       ├── logout()
│       └── verifyToken()
│
└── Booking Store
    ├── State
    │   ├── currentEvent
    │   ├── reservation
    │   ├── bookings
    │   ├── loading
    │   └── error
    │
    └── Actions
        ├── loadEvent()
        ├── reserveSeats()
        ├── capturePayment()
        ├── loadUserBookings()
        ├── getReservationStatus()
        └── clearReservation()
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                         User Actions                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Vue Components                          │
│  (LoginView, EventsView, BookingView, BookingsView)         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       Pinia Stores                           │
│              (authStore, bookingStore)                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      API Service Layer                       │
│          (services/api.js with Axios client)                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Request Interceptor                       │
│           (Add JWT token to Authorization header)            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     HTTP Request (Axios)                     │
│                    to API Gateway (port 8000)                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       Backend Services                       │
│    (Auth, Booking, Booking Status, Payment, etc.)           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     HTTP Response (JSON)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Response Interceptor                       │
│         (Handle errors, redirect on 401, etc.)              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Update Store State                           │
│            (Reactive data updates components)                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      UI Re-renders                           │
│              (Vue reactivity system)                         │
└─────────────────────────────────────────────────────────────┘
```

## Routing Flow

```
User Navigates
     │
     ▼
┌────────────────────┐
│   Router Guard     │◄─── Check authentication
│ (beforeEach hook)  │
└────────────────────┘
     │
     ├─── Not Authenticated + Protected Route ──► Redirect to /login
     │
     ├─── Authenticated + /login ──────────────► Redirect to /events
     │
     └─── Authorized ───────────────────────────► Load Route Component
                                                        │
                                                        ▼
                                              ┌──────────────────┐
                                              │  Route Component  │
                                              │  (Lazy Loaded)   │
                                              └──────────────────┘
```

## Authentication Flow

```
┌─────────────────────┐
│   User Visits App   │
└─────────────────────┘
          │
          ▼
    ┌──────────┐
    │  Router  │
    └──────────┘
          │
          ├─── Has Token in localStorage? ────► YES ─┐
          │                                           │
          └─── NO ──────────────────────────────────►│
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │   LoginView      │
                                            └──────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │  User Submits    │
                                            │  Credentials     │
                                            └──────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │  authStore.login │
                                            └──────────────────┘
                                                      │
                                                      ▼
                                            ┌──────────────────┐
                                            │  POST /auth/login│
                                            └──────────────────┘
                                                      │
                                                      ├─── Success ─► Store Token
                                                      │                    │
                                                      │                    ▼
                                                      │              Redirect to /events
                                                      │
                                                      └─── Error ───► Show Error Message
```

## Booking Flow Sequence

```
EventsView
    │
    │ User clicks "Book Now"
    ▼
BookingView (Step 1: Select)
    │
    │ 1. Select number of seats
    │ 2. Choose preferred row
    │ 3. View seat map
    │ 4. Click "Reserve Seats"
    ▼
bookingStore.reserveSeats()
    │
    │ POST /booking/bookings/reserve
    ▼
Reservation Created
    │
    ▼
BookingView (Step 2: Payment)
    │
    │ 1. View reservation details
    │ 2. Select payment method
    │ 3. Click "Pay Now"
    ▼
bookingStore.capturePayment()
    │
    │ POST /booking/payments/capture
    ▼
Payment Processed
    │
    ▼
BookingView (Step 3: Confirmation)
    │
    │ 1. View confirmation
    │ 2. Display booking ID
    │ 3. Option to view bookings or book more
    ▼
User Choice
    │
    ├─── "View My Bookings" ──► Navigate to /bookings
    │
    └─── "Book More Events" ──► Navigate to /events
```

## Reusable Components

```
BaseButton
├── Props
│   ├── variant (primary, secondary, danger, success)
│   ├── loading (boolean)
│   ├── disabled (boolean)
│   └── block (boolean)
└── Features
    ├── Loading spinner animation
    ├── Hover effects
    ├── Disabled states
    └── Click event emission

BaseInput
├── Props
│   ├── modelValue (v-model)
│   ├── type (text, email, password, etc.)
│   ├── label
│   ├── placeholder
│   ├── required
│   ├── disabled
│   └── error
└── Features
    ├── Two-way binding with v-model
    ├── Error message display
    ├── Focus states
    └── Validation styling

BaseCard
├── Props
│   ├── title
│   └── hover (boolean)
├── Slots
│   ├── default (body content)
│   └── footer
└── Features
    ├── Header with title
    ├── Flexible body content
    ├── Optional footer
    └── Hover animation
```

## API Service Structure

```
services/api.js
│
├── Axios Instance
│   ├── Base URL: VITE_API_URL
│   └── Default Headers
│
├── Interceptors
│   ├── Request Interceptor
│   │   └── Add JWT token to headers
│   │
│   └── Response Interceptor
│       ├── Handle success responses
│       └── Handle error responses
│           └── Redirect to login on 401
│
└── API Methods
    │
    ├── authAPI
    │   ├── register(userData)
    │   ├── login(credentials)
    │   └── verify()
    │
    ├── bookingAPI
    │   ├── getEvent(eventId)
    │   ├── reserve(data)
    │   └── capturePayment(data)
    │
    └── statusAPI
        ├── getReservation(reservationId)
        ├── getBooking(bookingId)
        └── getUserBookings(params)
```

## Technology Stack

```
┌─────────────────────────────────────────┐
│          Vue 3 (Composition API)         │
│     Progressive JavaScript Framework     │
└─────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
┌──────────┐  ┌─────────┐  ┌──────────┐
│ Vue      │  │ Pinia   │  │ Axios    │
│ Router   │  │ (State) │  │ (HTTP)   │
└──────────┘  └─────────┘  └──────────┘
        │           │           │
        └───────────┼───────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │        Vite           │
        │   (Build Tool + HMR)  │
        └───────────────────────┘
```

## Key Design Patterns

1. **Composition API**: Modern Vue 3 approach with `<script setup>`
2. **Store Pattern**: Centralized state management with Pinia
3. **Service Layer**: Separate API logic from components
4. **Component Composition**: Reusable UI components
5. **Route Guards**: Authentication checking before route access
6. **Interceptors**: Centralized request/response handling
7. **Reactive State**: Vue's reactivity for automatic UI updates
8. **Lazy Loading**: Code splitting for optimal performance
