# compose/mysql/init/init.sql
CREATE DATABASE IF NOT EXISTS kdx DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER DATABASE kdx CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
Alter user 'demo'@'%' IDENTIFIED WITH mysql_native_password BY 'Ecs@demo123';
GRANT ALL PRIVILEGES ON kdx.* TO 'demo'@'%';
FLUSH PRIVILEGES;