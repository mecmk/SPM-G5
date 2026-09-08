import { useState } from "react";

export function badFormatExample(a: number, b: number): number {
  let result = a + b;
  if (result == 5) {
    console.log("bad formatting example")
    debugger
  }
  return result
}

function notAComponent() {
  if (Math.random() > 0.5) {
    const [value] = useState(0)
    return value
  }
  return 0
}

export default notAComponent
