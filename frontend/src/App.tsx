import { Route, Routes } from "react-router";
import ContactsPage from "./pages/ContactsPage";
import CapturePage from "./pages/CapturePage";
import ContactPage from "./pages/ContactPage";
import SettingsPage from "./pages/SettingsPage";
import SpeakPage from "./pages/SpeakPage";
import { AppBar, Page } from "./components/AppBar";
import { EmptyState, buttonClass } from "./components/ui";
import { Link } from "react-router";

export default function App() {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:text-navy-900"
      >
        Skip to content
      </a>
      <Routes>
        <Route path="/" element={<ContactsPage />} />
        <Route path="/new" element={<CapturePage />} />
        <Route path="/speak" element={<SpeakPage />} />
        <Route path="/c/:id" element={<ContactPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}

function NotFound() {
  return (
    <>
      <AppBar title="Not found" back="/" />
      <Page>
        <h1 className="text-title font-semibold">Page not found</h1>
        <EmptyState
          text="There's nothing at this address."
          action={
            <Link to="/" className={buttonClass("secondary")}>
              Go to contacts
            </Link>
          }
        />
      </Page>
    </>
  );
}
