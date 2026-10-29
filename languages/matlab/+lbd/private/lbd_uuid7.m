function id = lbd_uuid7()
%LBD_UUID7  A new UUID version 7 (RFC 9562), lower case: 48 bits of Unix time in
%   milliseconds, the version 7, then 74 random bits from the operating system's secure
%   source. The random bits are taken from java.util.UUID.randomUUID (SecureRandom), never
%   from MATLAB's rand, so rng(0) can't repeat an id.
ms = uint64(floor(posixtime(datetime('now', 'TimeZone', 'UTC')) * 1000));
t = lower(dec2hex(ms, 12));
r = char(java.util.UUID.randomUUID().toString());   % xxxxxxxx-xxxx-4xxx-Vxxx-xxxxxxxxxxxx
% 12 random bits after its version digit, its variant digit (10xx: 8, 9, a or b) with the
% 2 random bits in it, and its last 60 random bits
id = string([t(1:8) '-' t(9:12) '-7' r(16:18) '-' r(20:23) '-' r(25:36)]);
end
