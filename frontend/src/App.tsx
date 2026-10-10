import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { CallWorkspace } from "./pages/CallWorkspace";
import { ExampleNotice } from "./components/ExampleNotice";

export function App() {
  return (
    <BrowserRouter>
      <ExampleNotice />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/calls/:callId" element={<CallWorkspace />} />
      </Routes>
    </BrowserRouter>
  );
}
