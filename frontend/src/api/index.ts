import { api as referenceApi } from "./client";
import { pxtApi } from "./client.pixeltable";

const isPixeltable = import.meta.env.VITE_BACKEND === "pixeltable";

export const api = isPixeltable ? pxtApi : referenceApi;
