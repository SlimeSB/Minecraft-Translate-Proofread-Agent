import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import ReviewPage from "./pages/ReviewPage";
import GlossaryPage from "./pages/GlossaryPage";
import LogsPage from "./pages/LogsPage";
import TranslatePage from "./pages/TranslatePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/glossary" element={<GlossaryPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/translate" element={<TranslatePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
