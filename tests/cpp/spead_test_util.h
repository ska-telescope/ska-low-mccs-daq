// Helpers for driving consumer processPacket() paths in tests.
//
// SpeadPacket builds a wire-format SPEAD packet (header + immediate-address item
// pointers + payload) that a consumer's processPacket() can parse, mirroring
// what the firmware emits. Item values are packed into the 48-bit address field.

#ifndef SPEAD_TEST_UTIL_H
#define SPEAD_TEST_UTIL_H

#include <cstdint>
#include <cstring>
#include <vector>

#include "SPEAD.h"

class SpeadPacket {
public:
    // Add a SPEAD item (immediate addressing): `id` is the item id, `value` the
    // 48-bit payload carried in the address field.
    SpeadPacket &item(int id, uint64_t value)
    {
        items_.push_back({id, value});
        return *this;
    }

    // Set the raw payload bytes that follow the item pointers.
    SpeadPacket &payload(std::vector<uint8_t> bytes)
    {
        payload_ = std::move(bytes);
        return *this;
    }

    // Serialise to the on-wire byte layout:
    //   [8B header][8B item]*nitems[payload...]
    std::vector<uint8_t> build() const
    {
        const size_t nitems = items_.size();
        const size_t header_and_items = (nitems + 1) * SPEAD_ITEMLEN;
        std::vector<uint8_t> buf(header_and_items + payload_.size(), 0);

        // Header occupies the first 8-byte slot (item index 0).
        reinterpret_cast<uint64_t *>(buf.data())[0] = htonll(SPEAD_HEADER_BUILD(nitems));

        // Item pointers occupy slots 1..nitems.
        for (size_t k = 0; k < nitems; ++k)
            SPEAD_SET_ITEM(buf.data(), k + 1,
                           SPEAD_ITEM_BUILD(SPEAD_IMMEDIATEADDR, items_[k].first, items_[k].second));

        if (!payload_.empty())
            std::memcpy(buf.data() + header_and_items, payload_.data(), payload_.size());

        return buf;
    }

private:
    std::vector<std::pair<int, uint64_t>> items_;
    std::vector<uint8_t>                  payload_;
};

#endif  // SPEAD_TEST_UTIL_H
