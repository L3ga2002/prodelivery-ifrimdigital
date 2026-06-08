import { User } from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

export const DriverAvatar = ({ driver, size = "md", className = "", testId = "driver-avatar" }) => {
  const sizes = {
    sm: "h-10 w-10 text-sm",
    md: "h-14 w-14 text-base",
    lg: "h-20 w-20 text-xl",
  };
  const avatarUrl = driver?.avatar_url ? `${API_URL}${driver.avatar_url}` : null;
  const initials = (driver?.name || "L")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return (
    <div
      className={`${sizes[size] || sizes.md} overflow-hidden rounded-full border border-orange-200 bg-slate-100 text-slate-700 shadow-sm ${className}`}
      data-testid={testId}
    >
      {avatarUrl ? (
        <img
          src={avatarUrl}
          alt={driver?.name ? `Avatar ${driver.name}` : "Avatar livrator"}
          className="h-full w-full object-cover"
          data-testid={`${testId}-image`}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-orange-50 to-slate-200 font-black">
          {initials || <User className="h-5 w-5" />}
        </div>
      )}
    </div>
  );
};
