import categories from "@/backend/service_categories.json";
export const serviceCategories = categories;
export function serviceFor(category:string) { return categories.find(service => service.category === category) || categories[2]; }
