/**
 * Reads Vivenu's public event payload (GET vivenu.com/api/events/info/<eventId>)
 * and reports whether HYROX Mixed Relay tickets can be bought.
 *
 * `active` is not the sold-out signal: a sold-out ticket stays `active: true`.
 * The shop's own cart logic uses the remaining volume `v` instead, capped by
 * the volume left in the ticket's category, so a day is buyable only when
 * min(ticket.v, category.v) > 0. That matches what the shop renders as
 * "Unavailable" (checked against San Diego 2027 on 2026-11-19).
 *
 * A Mixed Relay purchase is one captain ticket ("HYROX MIXED RELAY | <day>")
 * plus three auto-added "HYROX MIXED RELAY TEAM MEMBER | <day>" tickets. The
 * captain ticket decides availability; the team-member count is reported so
 * the alert can say whether a full team of four fits.
 */

export const CAPTAIN = /^HYROX MIXED RELAY \| (.+)$/i;
export const TEAM_MEMBER = /^HYROX MIXED RELAY TEAM MEMBER \| (.+)$/i;
export const TEAM_SIZE = 4;

export class StructureError extends Error {}

const volume = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** Remaining volume for a ticket after its category cap; null when Vivenu gives no number. */
function remaining(ticket, categories) {
  const own = volume(ticket.v);
  const category = categories.get(ticket.categoryRef);
  const cap = category ? volume(category.v) : null;
  if (own === null) return cap;
  return cap === null ? own : Math.min(own, cap);
}

/**
 * @param {object} event Parsed Vivenu events/info payload.
 * @returns {{ days: Array<{day: string, ticketId: string, left: number, membersLeft: number|null, available: boolean}>, available: string[] }}
 */
export function mixedRelayStatus(event) {
  if (!event || !Array.isArray(event.tickets)) {
    throw new StructureError('Vivenu payload has no tickets array');
  }
  const categories = new Map((event.categories || []).map((c) => [c.ref, c]));
  const members = new Map();
  for (const ticket of event.tickets) {
    const match = ticket.active && TEAM_MEMBER.exec(ticket.name || '');
    if (match) members.set(match[1].trim().toLowerCase(), remaining(ticket, categories));
  }

  const days = [];
  for (const ticket of event.tickets) {
    if (!ticket.active || TEAM_MEMBER.test(ticket.name || '')) continue;
    const match = CAPTAIN.exec(ticket.name || '');
    if (!match) continue;
    const day = match[1].trim();
    const left = remaining(ticket, categories);
    if (left === null) {
      throw new StructureError(`No remaining volume on ${ticket.name}`);
    }
    days.push({
      day,
      ticketId: ticket._id || ticket.id,
      left,
      membersLeft: members.has(day.toLowerCase()) ? members.get(day.toLowerCase()) : null,
      available: left > 0,
    });
  }
  if (!days.length) {
    // Every Mixed Relay day vanishing at once is more likely a renamed ticket
    // than a sell-out (sold-out days stay listed with v = 0), so fail loudly.
    throw new StructureError('No active Mixed Relay ticket found');
  }
  return { days, available: days.filter((d) => d.available).map((d) => d.day) };
}

/** Days available now that were not available in `previous` (an array of day names). */
export function newOpenings(status, previous = []) {
  const before = new Set(previous);
  return status.days.filter((d) => d.available && !before.has(d.day));
}

/** One-line description of a day's opening, for the alert text. */
export function describe(opening) {
  const members = opening.membersLeft;
  const team = members === null ? '' :
    members >= TEAM_SIZE - 1 ? '' : ` (only ${members} team-member spot${members === 1 ? '' : 's'} left)`;
  return `${opening.day}: ${opening.left} left${team}`;
}
