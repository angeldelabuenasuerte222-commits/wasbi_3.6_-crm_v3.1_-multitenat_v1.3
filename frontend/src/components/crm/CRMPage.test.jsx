import React, { act } from "react";
import { createRoot } from "react-dom/client";

import CRMPage from "./CRMPage";
import axios from "axios";


jest.mock("axios", () => ({
  get: jest.fn(),
  post: jest.fn(),
  patch: jest.fn(),
  isAxiosError: (error) => Boolean(error && error.isAxiosError),
}));


const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

function setNativeValue(element, value) {
  const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
  const prototype = Object.getPrototypeOf(element);
  const prototypeSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  const setter = prototypeSetter || valueSetter;
  setter.call(element, value);
}

async function changeInputValue(input, value) {
  await act(async () => {
    setNativeValue(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await flushPromises();
  });
}


describe("CRMPage login validation", () => {
  let container;
  let root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
      await flushPromises();
    });
    container.remove();
  });

  it("shows a slug validation error before authenticating when the tenant does not exist", async () => {
    axios.get.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 404, data: { detail: "Configuracion no encontrada" } },
    });

    await act(async () => {
      root.render(<CRMPage />);
      await flushPromises();
    });

    const slugInput = container.querySelector('input[placeholder="slug (ej. cafe-minima)"]');
    const passwordInput = container.querySelector('input[placeholder="Contraseña"]');
    const form = container.querySelector("form");

    await changeInputValue(slugInput, "tenant-invalido");
    await changeInputValue(passwordInput, "TenantPass123!");

    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await flushPromises();
      await flushPromises();
    });

    expect(container.textContent).toContain('No existe un tenant activo con el slug "tenant-invalido".');
    expect(axios.get).toHaveBeenCalledTimes(1);
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/business/tenant-invalido"));
    expect(container.textContent).toContain("Acceso al CRM");
  });

  it("locks the slug input and reuses the same login when rendered for /crm/:slug", async () => {
    axios.get.mockResolvedValueOnce({ data: { business_name: "Cafe Minima" } });

    await act(async () => {
      root.render(<CRMPage initialSlug="cafe-minima" lockSlug />);
      await flushPromises();
      await flushPromises();
    });

    const slugInput = container.querySelector('input[placeholder="slug (ej. cafe-minima)"]');

    expect(container.textContent).toContain("Acceso al CRM");
    expect(container.textContent).toContain("cafe-minima");
    expect(slugInput.disabled).toBe(true);
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/business/cafe-minima"));
  });
});
