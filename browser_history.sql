
create database Browser_history;
use Browser_history;

-- Table user to store data of user

create table user(
	user_id int primary key auto_increment,
    user_name varchar(50) unique not null,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    
create table history(
	history_id bigint primary key auto_increment,
	user_id int not null,
    url varchar(2500) not null,
    visited_at datetime not null,
    title varchar(1000) ,
    visit_count int DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES user(user_id) on delete CASCADE
);

CREATE Table bookmarks(
    bookmark_id bigint PRIMARY key AUTO_INCREMENT,
    user_id int not null,
    url varchar(2500) not null,
    title varchar(1000),
    created_at datetime DEFAULT CURRENT_TIMESTAMP,
    history_id bigint,
    FOREIGN KEY (user_id) REFERENCES user(user_id),
    FOREIGN KEY (history_id) REFERENCES history(history_id) ON DELETE SET NULL

);
