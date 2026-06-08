import { Moon, Sun } from "lucide-react";
import { Button } from "./ui/button";
import { useTheme } from "../context/ThemeContext";

export const ThemeToggle = ({ dataTestId = "theme-toggle-button", compact = false }) => {
  const { isDark, toggleTheme } = useTheme();

  return (
    <Button
      type="button"
      variant="outline"
      size={compact ? "icon" : "sm"}
      onClick={toggleTheme}
      className="border-border/80 bg-card/85 backdrop-blur"
      aria-label={isDark ? "Schimbă la tema light" : "Schimbă la tema dark"}
      data-testid={dataTestId}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      {!compact && <span className="ml-2 hidden sm:inline">Tema: {isDark ? "Dark" : "Light"}</span>}
    </Button>
  );
};
