import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { CallWorkspace } from "./pages/CallWorkspace";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/calls/:callId" element={<CallWorkspace />} />
      </Routes>
    </BrowserRouter>
  );
}
