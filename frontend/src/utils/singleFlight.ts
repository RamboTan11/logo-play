export interface SingleFlightGate {
  tryEnter: () => boolean
  leave: () => void
}

export function createSingleFlightGate(): SingleFlightGate {
  let active = false
  return {
    tryEnter: () => {
      if (active) return false
      active = true
      return true
    },
    leave: () => { active = false },
  }
}
