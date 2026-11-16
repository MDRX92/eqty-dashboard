// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title Test EQTY (Base Sepolia only)
/// @notice Worthless test token for trying the guestbook on testnet. Anyone can call `faucet()`
///         to get 1,000 tEQTY. Implements the subset of ERC-20 + ERC20Burnable the guestbook needs,
///         with the same OpenZeppelin v5 error signatures as the real EQTY token.
/// @dev NEVER deploy this on mainnet.
contract TestEQTY {
    string public constant name = "Test EQTY";
    string public constant symbol = "tEQTY";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    error ERC20InsufficientBalance(address sender, uint256 balance, uint256 needed);
    error ERC20InsufficientAllowance(address spender, uint256 allowance, uint256 needed);

    function faucet() external {
        uint256 amount = 1_000 ether;
        totalSupply += amount;
        balanceOf[msg.sender] += amount;
        emit Transfer(address(0), msg.sender, amount);
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _move(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        _spend(from, value);
        _move(from, to, value);
        return true;
    }

    function burn(uint256 value) external {
        _burn(msg.sender, value);
    }

    function burnFrom(address account, uint256 value) external {
        _spend(account, value);
        _burn(account, value);
    }

    function _spend(address owner, uint256 value) private {
        uint256 a = allowance[owner][msg.sender];
        if (a != type(uint256).max) {
            if (a < value) revert ERC20InsufficientAllowance(msg.sender, a, value);
            allowance[owner][msg.sender] = a - value;
        }
    }

    function _move(address from, address to, uint256 value) private {
        uint256 b = balanceOf[from];
        if (b < value) revert ERC20InsufficientBalance(from, b, value);
        balanceOf[from] = b - value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }

    function _burn(address from, uint256 value) private {
        uint256 b = balanceOf[from];
        if (b < value) revert ERC20InsufficientBalance(from, b, value);
        balanceOf[from] = b - value;
        totalSupply -= value;
        emit Transfer(from, address(0), value);
    }
}
