import React, { act } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import axios from "axios";


jest.mock("axios", () => ({
  get: jest.fn(),
  post: jest.fn(),
  patch: jest.fn(),
  isAxiosError: (error) => Boolean(error && error.isAxiosError),
}));

jest.mock("framer-motion", () => {
  const React = require("react");
  const Passthrough = React.forwardRef(({ children, ...props }, ref) =>
    React.createElement("div", { ref, ...props }, children)
  );

  return {
    motion: new Proxy(
      {},
      {
        get: () => Passthrough,
      }
    ),
    AnimatePresence: ({ children }) => React.createElement(React.Fragment, null, children),
  };
});

jest.mock(
  "react-router-dom",
  () => {
    const React = require("react");

    const getPath = () => global.location.pathname || "/";

    const BrowserRouter = ({ children }) => React.createElement(React.Fragment, null, children);

    const Route = () => null;

    const matches = (routePath, currentPath) => {
      if (routePath === "/crm" && currentPath === "/crm") return true;
      if (routePath === "/crm/:slug" && /^\/crm\/[^/]+$/.test(currentPath)) return true;
      if (routePath === "/internal/tenants" && currentPath === "/internal/tenants") return true;
      if (routePath === "/:slug?") return !currentPath.startsWith("/crm") && currentPath !== "/internal/tenants";
      return false;
    };

    const Routes = ({ children }) => {
      const currentPath = getPath();
      const route = React.Children.toArray(children)
        .filter((child) => React.isValidElement(child) && child.props)
        .find((child) => matches(child.props.path, currentPath));
      return route ? route.props.element : null;
    };

    const useParams = () => {
      const currentPath = getPath();
      if (/^\/crm\/[^/]+$/.test(currentPath)) {
        return { slug: currentPath.split("/")[2] };
      }
      if (/^\/[^/]+$/.test(currentPath)) {
        return { slug: currentPath.slice(1) };
      }
      return {};
    };

    return { BrowserRouter, Route, Routes, useParams };
  },
  { virtual: true }
);


const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

async function renderAtPath(root, path) {
  window.history.pushState({}, "", path);
  await act(async () => {
    root.render(<App />);
    await flushPromises();
    await flushPromises();
  });
}


describe("App routing error states", () => {
  let container;
  let root;
  let consoleErrorSpy;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();
    consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
      await flushPromises();
    });
    container.remove();
    window.history.pushState({}, "", "/");
    consoleErrorSpy.mockRestore();
  });

  it("shows a clear message when the public slug does not exist", async () => {
    axios.get.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 404, data: { detail: "Configuracion no encontrada" } },
    });

    await renderAtPath(root, "/slug-invalido");

    expect(container.textContent).toContain("Negocio no disponible");
    expect(container.textContent).toContain('slug-invalido');
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/business/slug-invalido"));
  });

  it("shows a clear message when the tenant CRM slug is invalid", async () => {
    axios.get.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 404, data: { detail: "Configuracion no encontrada" } },
    });

    await renderAtPath(root, "/crm/slug-invalido");

    expect(container.textContent).toContain("Slug no disponible");
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/business/slug-invalido"));
  });

  it("reuses the shared CRM login flow for tenant-specific routes", async () => {
    axios.get.mockResolvedValueOnce({ data: { business_name: "Cafe Minima" } });

    await renderAtPath(root, "/crm/cafe-minima");

    expect(container.textContent).toContain("Acceso al CRM");
    expect(container.textContent).toContain("cafe-minima");
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/business/cafe-minima"));
  });
});
