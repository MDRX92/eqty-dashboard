// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IERC20Burnable {
    function burnFrom(address account, uint256 value) external;
}

/// @title EQTY Guestbook
/// @notice Leave a short public message on Base by burning a small, fixed amount of EQTY.
/// @dev Deliberately minimal:
///      - no owner, no admin functions, no upgrades: nobody can change the fee or the token later;
///      - holds no tokens and no ETH (all functions are non-payable; the fee is burned directly
///        from the poster's wallet via `burnFrom`, which needs an `approve` of exactly `fee`);
///      - rejects links (`http`, `www.`, `://`), control characters and messages over MAX_BYTES.
///      The website limits messages to 140 characters; MAX_BYTES leaves room for multi-byte
///      UTF-8 characters (é, emoji) without letting anyone post essays.
///      Hiding abusive messages is done on the website (transparent hide list), not on-chain.
contract EQTYGuestbook {
    struct Message {
        address author;
        uint64 timestamp;
        string text;
    }

    uint256 public constant MAX_BYTES = 560;

    IERC20Burnable public immutable token;
    uint256 public immutable fee;

    Message[] private _messages;

    event Posted(uint256 indexed id, address indexed author, string text);

    error EmptyMessage();
    error MessageTooLong();
    error LinksNotAllowed();
    error InvalidCharacter();
    error ZeroAddress();

    constructor(address token_, uint256 fee_) {
        if (token_ == address(0)) revert ZeroAddress();
        token = IERC20Burnable(token_);
        fee = fee_;
    }

    /// @notice Post a message. Burns `fee` EQTY from the sender (approve exactly `fee` first).
    function post(string calldata text) external returns (uint256 id) {
        _validate(bytes(text));

        id = _messages.length;
        _messages.push(Message({author: msg.sender, timestamp: uint64(block.timestamp), text: text}));
        emit Posted(id, msg.sender, text);

        // Interaction last. Reverts (and undoes the post) if allowance or balance is too low.
        if (fee > 0) token.burnFrom(msg.sender, fee);
    }

    /// @notice Number of messages posted so far.
    function count() external view returns (uint256) {
        return _messages.length;
    }

    /// @notice Read one message (ids start at 0).
    function messageAt(uint256 id) external view returns (address author, uint64 timestamp, string memory text) {
        Message storage m = _messages[id];
        return (m.author, m.timestamp, m.text);
    }

    function _validate(bytes calldata b) private pure {
        uint256 n = b.length;
        if (n == 0) revert EmptyMessage();
        if (n > MAX_BYTES) revert MessageTooLong();

        for (uint256 i; i < n; ++i) {
            bytes1 c = b[i];
            // ASCII control characters (incl. newlines and DEL) are not allowed.
            if (c < 0x20 || c == 0x7f) revert InvalidCharacter();
            // "://"
            if (c == ":" && i + 2 < n && b[i + 1] == "/" && b[i + 2] == "/") revert LinksNotAllowed();
            // "http" and "www." (case-insensitive)
            if (i + 3 < n) {
                bytes1 c0 = _lower(c);
                bytes1 c1 = _lower(b[i + 1]);
                bytes1 c2 = _lower(b[i + 2]);
                bytes1 c3 = _lower(b[i + 3]);
                if (c0 == "h" && c1 == "t" && c2 == "t" && c3 == "p") revert LinksNotAllowed();
                if (c0 == "w" && c1 == "w" && c2 == "w" && c3 == ".") revert LinksNotAllowed();
            }
        }
    }

    function _lower(bytes1 c) private pure returns (bytes1) {
        return (c >= "A" && c <= "Z") ? bytes1(uint8(c) + 32) : c;
    }
}
