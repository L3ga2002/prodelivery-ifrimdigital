import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { toast } from "sonner";
import { Lock, Download, UserRound, Eye, Bike } from "lucide-react";

const ProDeliveryLoginMark = () => (
  <div className="inline-flex flex-col items-center" data-testid="login-logo">
    <div className="relative h-20 w-36">
      <span className="absolute left-0 top-8 h-1.5 w-12 rounded-full bg-white" />
      <span className="absolute left-4 top-12 h-1.5 w-8 rounded-full bg-white" />
      <Bike className="absolute left-12 top-1 h-20 w-20 text-white drop-shadow" strokeWidth={2.8} />
    </div>
    <div className="text-4xl font-black tracking-tight"><span className="text-slate-700">Pro</span><span className="text-orange-600">Delivery</span></div>
  </div>
);

const SHOW_DEMO_LOGIN = (
  process.env.NODE_ENV === "development" &&
  process.env.REACT_APP_ENABLE_DEMO_LOGIN === "true"
);

const DEMO_CREDENTIALS = SHOW_DEMO_LOGIN
  ? {
      admin: {
        email: process.env.REACT_APP_DEMO_ADMIN_EMAIL,
        password: process.env.REACT_APP_DEMO_ADMIN_PASSWORD,
      },
      driver: {
        email: process.env.REACT_APP_DEMO_DRIVER_1_EMAIL,
        password: process.env.REACT_APP_DEMO_DRIVER_PASSWORD,
      },
      restaurant: {
        email: process.env.REACT_APP_DEMO_RESTAURANT_1_EMAIL,
        password: process.env.REACT_APP_DEMO_RESTAURANT_PASSWORD,
      },
    }
  : {};

// PWA Install prompt
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
});

const LoginPage = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [canInstall, setCanInstall] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const hasDemoCredentials = Object.values(DEMO_CREDENTIALS).every(
    (account) => account.email && account.password,
  );

  // Check if PWA can be installed
  useEffect(() => {
    const checkInstall = () => {
      setCanInstall(!!deferredPrompt);
    };
    checkInstall();
    window.addEventListener('beforeinstallprompt', checkInstall);
    return () => window.removeEventListener('beforeinstallprompt', checkInstall);
  }, []);

  const installPWA = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      toast.success('Aplicație instalată cu succes!');
      setCanInstall(false);
    }
    deferredPrompt = null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    const result = await login(email, password);

    if (result.success) {
      toast.success(`Bine ai venit, ${result.user.name}!`);
      if (result.user.role === "admin") {
        navigate("/admin");
      } else if (result.user.role === "driver") {
        navigate("/driver");
      } else if (result.user.role === "restaurant") {
        navigate("/restaurant");
      }
    } else {
      toast.error(result.error);
    }

    setIsLoading(false);
  };

  const handleDemoLogin = async (role) => {
    setIsLoading(true);
    const demoAccount = DEMO_CREDENTIALS[role];

    if (!demoAccount?.email || !demoAccount?.password) {
      toast.error("Credențialele demo nu sunt configurate.");
      setIsLoading(false);
      return;
    }

    const result = await login(demoAccount.email, demoAccount.password);

    if (result.success) {
      toast.success(`Bine ai venit, ${result.user.name}!`);
      if (result.user.role === "admin") {
        navigate("/admin");
      } else if (result.user.role === "restaurant") {
        navigate("/restaurant");
      } else {
        navigate("/driver");
      }
    } else {
      toast.error(result.error);
    }

    setIsLoading(false);
  };

  return (
    <div className="min-h-screen bg-neutral-200 text-slate-900">
      <div className="relative mx-auto flex min-h-screen w-full max-w-md flex-col overflow-hidden bg-[#eeeeee] shadow-2xl" data-testid="login-card">
        <div className="absolute -left-20 -top-20 h-56 w-[38rem] rotate-[-10deg] rounded-[50%] bg-orange-600" />
        <div className="absolute -bottom-24 -right-32 h-48 w-[42rem] rotate-[-8deg] rounded-[50%] bg-orange-600" />
        <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-32 bg-[linear-gradient(to_top,rgba(148,163,184,0.45),transparent)]" />

        <div className="relative z-10 flex flex-1 flex-col justify-center px-8 py-10">
          <div className="mb-10 text-center">
            <ProDeliveryLoginMark />
            <h1 className="mt-4 text-4xl font-black tracking-tight">Bun Venit!</h1>
            <p className="mt-2 text-lg font-semibold text-slate-500">Conectează-te pentru a continua!</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <UserRound className="absolute left-5 top-1/2 h-6 w-6 -translate-y-1/2 text-slate-500" />
              <Input
                id="email"
                type="text"
                placeholder="Număr de telefon sau mail"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-16 rounded-2xl border-0 bg-white pl-16 text-base font-semibold shadow-lg placeholder:text-slate-400"
                required
                data-testid="email-input"
              />
            </div>
            <div className="relative">
              <Lock className="absolute left-5 top-1/2 h-6 w-6 -translate-y-1/2 text-slate-500" />
              <Input
                id="password"
                type="password"
                placeholder="Parola"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-16 rounded-2xl border-0 bg-white pl-16 pr-14 text-base font-semibold shadow-lg placeholder:text-slate-400"
                required
                data-testid="password-input"
              />
              <Eye className="absolute right-5 top-1/2 h-6 w-6 -translate-y-1/2 text-slate-500" />
            </div>
            <button type="button" onClick={() => toast.info("Resetarea parolei va fi activată din panoul admin.")} className="block w-full text-center text-sm font-black text-orange-600" data-testid="forgot-password-button">ai uitat parola?</button>
            <Button type="submit" className="h-16 w-full rounded-2xl bg-orange-600 text-lg font-black shadow-xl hover:bg-orange-700" disabled={isLoading} data-testid="login-button">
              {isLoading ? "Se conectează..." : "Conectează-te"}
            </Button>
          </form>

          {SHOW_DEMO_LOGIN && (
            <>
              <div className="relative my-6">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-[#eeeeee] px-2 text-slate-500">sau acces demo</span>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <Button
                  variant="outline"
                  onClick={() => handleDemoLogin("admin")}
                  disabled={isLoading || !hasDemoCredentials}
                  className="h-11 rounded-xl bg-white text-xs"
                  data-testid="demo-admin-button"
                >
                  Demo Admin
                </Button>
                <Button
                  variant="outline"
                  onClick={() => handleDemoLogin("driver")}
                  disabled={isLoading || !hasDemoCredentials}
                  className="h-11 rounded-xl bg-white text-xs"
                  data-testid="demo-driver-button"
                >
                  Demo Livrator
                </Button>
                <Button
                  variant="outline"
                  onClick={() => handleDemoLogin("restaurant")}
                  disabled={isLoading || !hasDemoCredentials}
                  className="h-11 rounded-xl bg-white text-xs"
                  data-testid="demo-restaurant-button"
                >
                  Demo Restaurant
                </Button>
              </div>

              {hasDemoCredentials && (
                <div className="mt-4 rounded-xl bg-white/70 px-3 py-2 text-center text-[10px] font-semibold text-slate-500">
                  Demo credentials are loaded from local env only.
                </div>
              )}
            </>
          )}

          {!SHOW_DEMO_LOGIN && (
            <div className="my-6">
              <span className="block w-full border-t" />
            </div>
          )}

          {canInstall && (
            <Button
              variant="outline"
              onClick={installPWA}
              className="w-full h-11"
              data-testid="install-pwa-button"
            >
              <Download className="w-4 h-4 mr-2" />
              Instalează Aplicația
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
