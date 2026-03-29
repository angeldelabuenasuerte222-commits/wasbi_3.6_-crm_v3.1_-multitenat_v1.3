import { TextDecoder, TextEncoder } from "util";

global.IS_REACT_ACT_ENVIRONMENT = true;

if (!global.TextEncoder) {
  global.TextEncoder = TextEncoder;
}

if (!global.TextDecoder) {
  global.TextDecoder = TextDecoder;
}

if (!window.scrollTo) {
  window.scrollTo = jest.fn();
}
