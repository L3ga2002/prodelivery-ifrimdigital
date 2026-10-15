import axios from "axios";

// Recovery owns its retries. This client must never inherit the shared
// AuthProvider refresh/replay interceptor or retain an old bearer token.
export const createRecoveryTransport = ({ apiUrl, actorId, getToken }) => {
  const transport = axios.create({ withCredentials: true });
  const authenticated = (options) => {
    const token = getToken();
    return { ...options, headers: {
      Authorization: token ? `Bearer ${token}` : null,
      "X-Expected-Actor-ID": actorId,
    } };
  };
  return {
    get: (path, options) => transport.get(`${apiUrl}${path}`, authenticated(options)),
    post: (path, body, options) => transport.post(`${apiUrl}${path}`, body, authenticated(options)),
    put: (path, body, options) => transport.put(`${apiUrl}${path}`, body, authenticated(options)),
  };
};
