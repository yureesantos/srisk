/* The one currency control. Sits in the topbar; every money figure follows it. */

import { Coins } from 'lucide-react'
import { useCurrency } from './currency'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select'

export function CurrencySelect() {
  const { currency, setCurrency, available } = useCurrency()

  return (
    <Select value={currency} onValueChange={setCurrency}>
      <SelectTrigger
        aria-label="Display currency"
        className="h-8 w-[104px] gap-1.5 px-2.5"
      >
        <Coins className="size-3.5 shrink-0 text-bronze" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {available.map((code) => (
          <SelectItem key={code} value={code} className="tnum">
            {code}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
