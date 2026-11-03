import React from 'react';
import { View } from 'react-native';
import { colors, spacing } from '../core/theme';
import { formatPaise, lineTotal, parseQuantity, parseRupees } from '../core/money';
import { newId, nowIso } from '../core/ids';
import { parseDay } from '../core/dates';
import { AppText, Button, Card } from './components/ui';
import { TextField } from './components/TextField';

export interface ItemRow {
  key: string;
  name: string;
  qty: string;
  unit: string;
  price: string;
  discount: string;
}

export const emptyItem = (): ItemRow => ({ key: newId(), name: '', qty: '1', unit: 'pc', price: '', discount: '' });

export interface ParsedItem {
  itemName: string;
  quantityMilli: number;
  unit: string;
  unitPricePaise: number;
  discountPaise: number;
  lineGrossPaise: number;
  lineTotalPaise: number;
}

/** Parses rows into exact integer values, or returns the first validation error. */
export function parseItems(rows: ItemRow[]): { items: ParsedItem[] } | { error: string } {
  const items: ParsedItem[] = [];
  for (const [i, r] of rows.entries()) {
    const n = i + 1;
    if (!r.name.trim()) return { error: `Item ${n}: enter a name` };
    const qty = parseQuantity(r.qty);
    if (qty === null) return { error: `Item ${n}: enter a valid quantity` };
    const price = parseRupees(r.price);
    if (price === null || price <= 0) return { error: `Item ${n}: enter a valid price` };
    const disc = r.discount.trim() ? parseRupees(r.discount) : 0;
    if (disc === null) return { error: `Item ${n}: invalid discount` };
    const gross = lineTotal(price, qty);
    if (disc > gross) return { error: `Item ${n}: discount is more than the item total` };
    items.push({
      itemName: r.name.trim(), quantityMilli: qty, unit: r.unit.trim(), unitPricePaise: price,
      discountPaise: disc, lineGrossPaise: gross, lineTotalPaise: gross - disc,
    });
  }
  return { items };
}

/** Blank = now. A typed day (YYYY-MM-DD) is combined with the current time; the future is rejected. */
export function resolveWhen(text: string): { iso: string } | { error: string } {
  if (!text.trim()) return { iso: nowIso() };
  const d = parseDay(text);
  if (!d) return { error: 'Enter the date as YYYY-MM-DD' };
  const now = new Date();
  d.setHours(now.getHours(), now.getMinutes(), now.getSeconds());
  if (d.getTime() > now.getTime()) return { error: 'Date cannot be in the future' };
  return { iso: d.toISOString() };
}

interface EditorProps {
  rows: ItemRow[];
  onChange: (rows: ItemRow[]) => void;
  allowDiscount?: boolean;
}

export function ItemsEditor({ rows, onChange, allowDiscount }: EditorProps) {
  const set = (key: string, patch: Partial<ItemRow>) =>
    onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <View style={{ gap: spacing.md }}>
      {rows.map((r, idx) => {
        const qty = parseQuantity(r.qty);
        const price = parseRupees(r.price);
        const disc = r.discount.trim() ? parseRupees(r.discount) : 0;
        const total = qty !== null && price !== null ? lineTotal(price, qty) - (disc ?? 0) : null;
        return (
          <Card key={r.key}>
            <TextField label={`Item ${idx + 1} name`} value={r.name} onChangeText={(t) => set(r.key, { name: t })} />
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <View style={{ flex: 1 }}>
                <TextField label="Qty" keyboardType="decimal-pad" value={r.qty} onChangeText={(t) => set(r.key, { qty: t })} />
              </View>
              <View style={{ flex: 1 }}>
                <TextField label="Unit" value={r.unit} onChangeText={(t) => set(r.key, { unit: t })} />
              </View>
            </View>
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <View style={{ flex: 1 }}>
                <TextField label="Unit price" prefix="₹" keyboardType="decimal-pad" value={r.price} onChangeText={(t) => set(r.key, { price: t })} />
              </View>
              {allowDiscount ? (
                <View style={{ flex: 1 }}>
                  <TextField label="Discount" prefix="₹" keyboardType="decimal-pad" value={r.discount} onChangeText={(t) => set(r.key, { discount: t })} />
                </View>
              ) : null}
            </View>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm }}>
              <AppText variant="bodyStrong" color={colors.primary}>
                Line total: {total !== null ? formatPaise(total) : '—'}
              </AppText>
              {rows.length > 1 ? (
                <Button title="Remove" variant="ghost" onPress={() => onChange(rows.filter((x) => x.key !== r.key))} />
              ) : null}
            </View>
          </Card>
        );
      })}
      <Button title="+ Add another item" variant="secondary" onPress={() => onChange([...rows, emptyItem()])} />
    </View>
  );
}
