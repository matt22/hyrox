// Trimmed from vivenu.com/api/events/info/6ae9ed7c0d921b7c5db5a99b (San Diego
// 2027) on 2026-11-19, keeping the fields the parser reads.
export const RELAY = '8eb6b9f2-ae86-4e02-b799-f9977cb33c21';
export const SINGLES = 'singles-ref';

export function sanDiego({ friday = 0, members = 0, relayCategory = 104, extra = [] } = {}) {
  return {
    _id: '6ae9ed7c0d921b7c5db5a99b',
    saleStatus: 'onSale',
    categories: [
      { ref: SINGLES, name: 'Singles', v: 731 },
      { ref: RELAY, name: 'Relay', v: relayCategory },
    ],
    tickets: [
      { _id: 'men-fri', name: 'HYROX MEN | Friday', active: true, v: 0, categoryRef: SINGLES },
      { _id: 'mens-relay-fri', name: 'HYROX MENS RELAY | Friday', active: true, v: 5, categoryRef: RELAY },
      { _id: '6ae9ed7ca71b78574cb87ec2', name: 'HYROX MIXED RELAY | Friday', active: true, v: friday, categoryRef: RELAY },
      { _id: '6ae9ed7ca71b78574cb87ec3', name: 'HYROX MIXED RELAY TEAM MEMBER | Friday', active: true, v: members, categoryRef: RELAY, conditionalAvailability: true },
      ...extra,
    ],
  };
}
