import { useQuery } from '@tanstack/react-query';
import {
  getCustomer, getKhataSummary, getLedger, getSaleDetail, getSalesSummary, getShop, listCustomers, listSales,
} from '../core/db/repo';
import type { DateRange } from '../core/dates';

// All reads come from the local SQLite database (offline-first); sync invalidates these.
export const useShop = () => useQuery({ queryKey: ['shop'], queryFn: getShop });
export const useCustomers = (search: string) =>
  useQuery({ queryKey: ['customers', search], queryFn: () => listCustomers(search) });
export const useCustomer = (id: string) => useQuery({ queryKey: ['customer', id], queryFn: () => getCustomer(id) });
export const useLedger = (id: string) => useQuery({ queryKey: ['ledger', id], queryFn: () => getLedger(id) });
export const useKhataSummary = () => useQuery({ queryKey: ['khataSummary'], queryFn: getKhataSummary });
export const useSalesSummary = (r: DateRange) =>
  useQuery({ queryKey: ['salesSummary', r.fromIso, r.toIso], queryFn: () => getSalesSummary(r) });
export const useSales = (r: DateRange) =>
  useQuery({ queryKey: ['sales', r.fromIso, r.toIso], queryFn: () => listSales(r) });
export const useSaleDetail = (id: string) => useQuery({ queryKey: ['sale', id], queryFn: () => getSaleDetail(id) });
