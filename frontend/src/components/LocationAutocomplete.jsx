import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Loader2, MapPin, Search, X } from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;

export function LocationAutocomplete({ value, onChange, onSelect, placeholder = "Caută adresă în Bacău...", testIdPrefix = "location" }) {
  const [suggestions, setSuggestions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const timeoutRef = useRef(null);

  useEffect(() => {
    window.clearTimeout(timeoutRef.current);
    if (!value || value.trim().length < 2) {
      setSuggestions([]);
      setOpen(false);
      return undefined;
    }

    timeoutRef.current = window.setTimeout(async () => {
      setIsLoading(true);
      try {
        const response = await axios.get(`${API_URL}/api/geocoding/search`, {
          params: { q: value.trim(), limit: 6 },
        });
        setSuggestions(response.data.suggestions || []);
        setOpen(true);
        setActiveIndex(-1);
      } catch {
        setSuggestions([]);
      } finally {
        setIsLoading(false);
      }
    }, 350);

    return () => window.clearTimeout(timeoutRef.current);
  }, [value]);

  const selectSuggestion = (suggestion) => {
    onChange(suggestion.label);
    onSelect?.(suggestion);
    setSuggestions([]);
    setOpen(false);
  };

  const handleKeyDown = (event) => {
    if (!open || suggestions.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, suggestions.length - 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    }
    if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="relative" data-testid={`${testIdPrefix}-autocomplete`}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => suggestions.length > 0 && setOpen(true)}
          className="pl-9 pr-10"
          placeholder={placeholder}
          autoComplete="off"
          data-testid={`${testIdPrefix}-autocomplete-input`}
        />
        {isLoading ? (
          <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : value ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2"
            onClick={() => {
              onChange("");
              setOpen(false);
            }}
            data-testid={`${testIdPrefix}-autocomplete-clear-button`}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        ) : null}
      </div>
      {open && suggestions.length > 0 && (
        <div className="absolute z-[1200] mt-2 max-h-72 w-full overflow-y-auto rounded-lg border bg-card shadow-xl" data-testid={`${testIdPrefix}-autocomplete-results`}>
          {suggestions.map((suggestion, index) => (
            <button
              key={suggestion.place_id || `${suggestion.label}-${index}`}
              type="button"
              className={`flex w-full gap-2 px-3 py-2 text-left text-sm transition-colors ${activeIndex === index ? "bg-muted" : "hover:bg-muted/70"}`}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectSuggestion(suggestion)}
              data-testid={`${testIdPrefix}-autocomplete-option-${index}`}
            >
              <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-orange-600" />
              <span className="min-w-0">
                <span className="block truncate font-medium">{suggestion.name}</span>
                <span className="block line-clamp-2 text-xs text-muted-foreground">{suggestion.label}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
