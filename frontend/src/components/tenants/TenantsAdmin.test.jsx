import React, { act } from "react";
import { createRoot } from "react-dom/client";

import axios from "axios";

import TenantsAdmin from "./TenantsAdmin";


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

async function clickElement(element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flushPromises();
    await flushPromises();
  });
}


describe("TenantsAdmin system prompt flow", () => {
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

  it("loads and submits the tenant system prompt from the internal panel", async () => {
    axios.get
      .mockResolvedValueOnce({
        data: [{ slug: "tenant-a", business_name: "Tenant A", is_active: true, has_password: true }],
      })
      .mockResolvedValueOnce({
        data: {
          slug: "tenant-a",
          business_name: "Tenant A",
          phone: "",
          hours: "",
          address: "",
          avatar: "",
          image: "",
          greeting: "Hola",
          system_prompt: "Prompt interno",
          is_active: true,
        },
      })
      .mockResolvedValueOnce({
        data: [{ slug: "tenant-a", business_name: "Tenant A", is_active: true, has_password: true }],
      });
    axios.patch.mockResolvedValueOnce({ data: {} });

    await act(async () => {
      root.render(<TenantsAdmin />);
      await flushPromises();
    });

    const adminPasswordInput = container.querySelector('input[placeholder="Contraseña global admin"]');
    await changeInputValue(adminPasswordInput, "GlobalPass123!");

    const loadButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Cargar tenants"
    );
    await clickElement(loadButton);

    const editButton = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Editar"
    );
    await clickElement(editButton);

    const systemPromptTextarea = container.querySelector(
      'textarea[placeholder="Si lo dejas vacio al crear se usa el prompt seguro por defecto."]'
    );
    expect(systemPromptTextarea.value).toBe("Prompt interno");

    await changeInputValue(systemPromptTextarea, "Prompt actualizado");

    const form = container.querySelector("form");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await flushPromises();
      await flushPromises();
    });

    expect(axios.patch).toHaveBeenCalledWith(
      expect.stringContaining("/internal/tenants/tenant-a"),
      expect.objectContaining({ system_prompt: "Prompt actualizado" }),
      expect.objectContaining({
        headers: expect.objectContaining({ "x-admin-password": "GlobalPass123!" }),
      })
    );
  });
});
