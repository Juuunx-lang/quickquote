import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { Chat } from "./pages/Chat";

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Chat />} />
      </Routes>
    </Router>
  );
}
