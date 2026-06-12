import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import LoginPage from "./pages/LoginPage";
import AdminDashboard from "./pages/AdminDashboard";
import DriverApp from "./pages/DriverApp";
import RestaurantApp from "./pages/RestaurantApp";
import { ConnectionStatusBanner } from "./components/ConnectionStatusBanner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider, useTheme } from "./context/ThemeContext";
import "./App.css";

const suppressResizeObserverOverlay = (event) => {
  if (event.message?.includes("ResizeObserver loop completed")) {
    event.stopImmediatePropagation();
  }
};

window.addEventListener("error", suppressResizeObserverOverlay);

// Register Service Worker for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .then(() => {})
      .catch(() => {});
  });
}

// Protected Route Component
const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    // Redirect based on role
    if (user.role === "admin") return <Navigate to="/admin" replace />;
    if (user.role === "driver") return <Navigate to="/driver" replace />;
    if (user.role === "restaurant") return <Navigate to="/restaurant" replace />;
    return <Navigate to="/login" replace />;
  }

  return children;
};

// Home redirect based on role
const HomeRedirect = () => {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (user.role === "admin") return <Navigate to="/admin" replace />;
  if (user.role === "driver") return <Navigate to="/driver" replace />;
  if (user.role === "restaurant") return <Navigate to="/restaurant" replace />;

  return <Navigate to="/login" replace />;
};

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </ThemeProvider>
  );
}

const AppShell = () => {
  const { theme } = useTheme();

  return (
    <>
      <ConnectionStatusBanner />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <AdminDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/driver"
            element={
              <ProtectedRoute allowedRoles={["driver"]}>
                <DriverApp />
              </ProtectedRoute>
            }
          />
          <Route
            path="/restaurant"
            element={
              <ProtectedRoute allowedRoles={["restaurant"]}>
                <RestaurantApp />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<HomeRedirect />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-center" richColors theme={theme} />
    </>
  );
};

export default App;
